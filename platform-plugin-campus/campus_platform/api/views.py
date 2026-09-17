"""
Integration API called by the control plane. Authenticated with an Open edX OAuth2/JWT
token for the ``campus-integration`` service user, which must be a member of the
``CAMPUS_INTEGRATION_GROUP`` Django group (staff alone is not enough).

Learners are identified by the immutable identity-provider user id (OIDC ``sub``). ``username`` /
``email`` are accepted for operator tooling but ``sub`` is the contract.

POST /campus/api/v1/admissions/
  {"sub": "...", "course_id": "course-v1:ORG+CODE+RUN", "application_id": "APP-1",
   "institution": "ORG", "action": "submit" | "review" | "admit" | "decline" | "withdraw" | "defer"}
  -> 200 applied (learner has an LMS account, enrolment synced)
  -> 202 pending (no LMS account yet; applied automatically at first SSO login)
GET  /campus/api/v1/admissions/?sub=...&course_id=...

PUT  /campus/api/v1/roles/      {"sub": "...", "roles": ["instructor:course-v1:...", ...]}
  Synchronises detailed (per course run) entitlements; reconciles only API-sourced grants.
POST /campus/api/v1/users/status/   {"sub": "...", "status": "suspended" | "active", "reason": "..."}
  Immediate suspension: sessions, tokens and roles revoked; 403 on every request thereafter.

GET  /campus/api/v1/support/learners/?username=...   (institution support officer, session auth)
  Enrolment/progress summary for a learner, limited to the officer's SupportScope.

POST /campus/api/v1/institutions/   {"code": "ORG", "name": "...", "admin_email": "..."}
  Provision an institution: organisation, tenant config and host route (idempotent).
GET  /campus/api/v1/events/?since=<sequence>&limit=500   Pull outbox events for reconciliation.
POST /campus/api/v1/events/replay/   {"ids": [...]}      Re-queue events for webhook delivery.
GET  /campus/api/v1/dashboard/courses/   (learner, session auth)
  Listing metadata for the caller's own enrolments, used by the "My learning" cards.
GET  /campus/api/v1/dashboard/applications/   (learner, session auth)
  The caller's applications/admissions with status, for the "Applications" panel.
GET  /campus/api/v1/me/   (session auth; 401 when anonymous)
  Who the caller is and which "doors" to show: learner always, ``studio``/``teach`` for institution
  staff (from CourseAccessRole), ``console`` for institution administrators, ``admin`` for platform admins. Used by the product site header/sign-in
  page and the LMS/Studio header so navigation is role-aware without anyone self-declaring a role.

POST/PUT are idempotent: repeating a call converges on the same state, so the control plane may retry on
timeouts without side effects.
"""
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from edx_rest_framework_extensions.auth.jwt.authentication import JwtAuthentication
from edx_rest_framework_extensions.auth.session.authentication import SessionAuthenticationAllowInactiveUser
from opaque_keys import InvalidKeyError
from opaque_keys.edx.keys import CourseKey
from rest_framework import status
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from .. import events, hooks, identity, provisioning
from ..console import administered_institutions
from ..models import Admission, IdentityAudit, ManagedRole, OutboxEvent, SupportScope

User = get_user_model()

ACTION_TO_STATUS = {
    "submit": Admission.STATUS_SUBMITTED,
    "review": Admission.STATUS_UNDER_REVIEW,
    "admit": Admission.STATUS_ADMITTED,
    "decline": Admission.STATUS_DECLINED,
    "withdraw": Admission.STATUS_WITHDRAWN,
    "defer": Admission.STATUS_DEFERRED,
}


class IsCampusIntegration(BasePermission):
    """Staff service user in the integration group (institutions never call these endpoints)."""

    def has_permission(self, request, view):
        u = request.user
        return bool(
            u and u.is_authenticated and u.is_active and u.is_staff
            and u.groups.filter(name=settings.CAMPUS_INTEGRATION_GROUP).exists()
        )


class IntegrationView(APIView):
    authentication_classes = (JwtAuthentication, SessionAuthenticationAllowInactiveUser)
    permission_classes = (IsCampusIntegration,)

    def resolve_user(self, data):
        """(user, sub) from sub | username | email. user may be None when only a sub is known."""
        if sub := data.get("sub"):
            user = identity.user_for_sub(sub)
            return user, sub, None
        try:
            if "username" in data:
                user = User.objects.get(username=data["username"])
            else:
                user = User.objects.get(email__iexact=data["email"])
        except KeyError:
            return None, None, Response({"error": "sub (or username/email) is required"}, status=status.HTTP_400_BAD_REQUEST)
        except User.DoesNotExist:
            return None, None, Response({"error": "unknown user"}, status=status.HTTP_404_NOT_FOUND)
        except User.MultipleObjectsReturned:
            return None, None, Response(
                {"error": "email matches several accounts; use sub or username"},
                status=status.HTTP_409_CONFLICT,
            )
        return user, identity.sub_for_user(user), None


def _serialize(adm):
    return {
        "sub": adm.identity_sub,
        "username": adm.user.username if adm.user else None,
        "course_id": str(adm.course_key),
        "application_id": adm.application_id,
        "institution": adm.institution,
        "status": adm.status,
        "status_label": adm.get_status_display(),
        "pending": adm.is_pending,
        "modified": adm.modified.isoformat(),
    }


class AdmissionsView(IntegrationView):
    def get(self, request):
        qs = Admission.objects.select_related("user")
        if sub := request.query_params.get("sub"):
            qs = qs.filter(identity_sub=sub)
        if username := request.query_params.get("username"):
            qs = qs.filter(user__username=username)
        if course_id := request.query_params.get("course_id"):
            try:
                qs = qs.filter(course_key=CourseKey.from_string(course_id))
            except InvalidKeyError:
                return Response({"error": "invalid course_id"}, status=status.HTTP_400_BAD_REQUEST)
        return Response([_serialize(a) for a in qs[:500]])

    def post(self, request):
        data = request.data
        action = data.get("action", "admit")
        if action not in ACTION_TO_STATUS:
            return Response({"error": f"unknown action {action!r}"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            course_key = CourseKey.from_string(data["course_id"])
        except (KeyError, InvalidKeyError, TypeError):
            return Response({"error": "a valid course_id is required"}, status=status.HTTP_400_BAD_REQUEST)
        user, sub, error = self.resolve_user(data)
        if error:
            return error
        institution = data.get("institution", course_key.org)
        if institution != course_key.org:
            # The course run belongs to another institution's Open edX organisation.
            return Response(
                {"error": f"course {course_key} is not owned by institution {institution!r}"},
                status=status.HTTP_403_FORBIDDEN,
            )
        if user is not None and not user.is_active and action == "admit":
            return Response({"error": "user account is suspended"}, status=status.HTTP_409_CONFLICT)

        defaults = {
            "application_id": data.get("application_id", ""),
            "institution": institution,
            "status": ACTION_TO_STATUS[action],
            "mode": data.get("mode", "honor"),
        }
        with transaction.atomic():
            if user is not None:
                adm, _ = Admission.objects.update_or_create(user=user, course_key=course_key, defaults={**defaults, "identity_sub": sub})
            else:
                adm, _ = Admission.objects.update_or_create(identity_sub=sub, course_key=course_key, user=None, defaults=defaults)
            identity.sync_enrolment(adm)

        return Response(_serialize(adm), status=status.HTTP_202_ACCEPTED if adm.is_pending else status.HTTP_200_OK)


class RolesView(IntegrationView):
    def get(self, request):
        user, sub, error = self.resolve_user(request.query_params)
        if error:
            return error
        if user is None:
            return Response({"error": "no LMS account for this sub yet"}, status=status.HTTP_404_NOT_FOUND)
        return Response(_roles_payload(user, sub))

    def put(self, request):
        data = request.data
        roles = data.get("roles")
        if not isinstance(roles, list) or not all(isinstance(r, str) for r in roles):
            return Response({"error": "roles must be a list of claim strings"}, status=status.HTTP_400_BAD_REQUEST)
        if "platform_admin" in roles:
            return Response({"error": "platform_admin is only granted via the login claim"}, status=status.HTTP_400_BAD_REQUEST)
        user, sub, error = self.resolve_user(data)
        if error:
            return error
        if user is None:
            return Response({"error": "no LMS account for this sub yet"}, status=status.HTTP_404_NOT_FOUND)
        if not user.is_active:
            return Response({"error": "user account is suspended"}, status=status.HTTP_409_CONFLICT)
        identity.apply_roles(user, roles, ManagedRole.SOURCE_API, actor=request.user.username)
        return Response(_roles_payload(user, sub))


def _roles_payload(user, sub):
    return {
        "sub": sub,
        "username": user.username,
        "is_active": user.is_active,
        "roles": [
            {"role": m.role, "org": m.org, "course_id": m.course_id, "source": m.source}
            for m in ManagedRole.objects.filter(user=user).order_by("source", "org", "course_id", "role")
        ],
        "support_scopes": [
            {"institution": s.institution, "course_id": s.course_id, "source": s.source}
            for s in SupportScope.objects.filter(user=user)
        ],
    }


class UserStatusView(IntegrationView):
    def post(self, request):
        data = request.data
        new_status = data.get("status")
        if new_status not in ("suspended", "active"):
            return Response({"error": "status must be 'suspended' or 'active'"}, status=status.HTTP_400_BAD_REQUEST)
        user, sub, error = self.resolve_user(data)
        if error:
            return error
        if user is None:
            return Response({"error": "no LMS account for this sub yet"}, status=status.HTTP_404_NOT_FOUND)
        if user.is_superuser or user == request.user:
            return Response({"error": "refusing to change this account"}, status=status.HTTP_403_FORBIDDEN)
        active = new_status == "active"
        if user.is_active != active:
            identity.set_account_status(user, active, actor=request.user.username, reason=data.get("reason", ""))
        return Response({"sub": sub, "username": user.username, "status": "active" if user.is_active else "suspended"})


class SupportLearnerView(APIView):
    """
    OEC support: read-only learner summary limited to the officer's SupportScope. No grades,
    no PII beyond username/name, no learners outside the officer's institutions/runs.
    """

    authentication_classes = (JwtAuthentication, SessionAuthentication)
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        from common.djangoapps.student.models import CourseEnrollment  # pylint: disable=import-outside-toplevel

        scopes = list(SupportScope.objects.filter(user=request.user))
        if not scopes:
            return Response({"error": "no support scope"}, status=status.HTTP_403_FORBIDDEN)
        username = request.query_params.get("username")
        if not username:
            return Response({"error": "username is required"}, status=status.HTTP_400_BAD_REQUEST)
        learner = User.objects.filter(username=username).first()
        if learner is None:
            return Response({"error": "not found"}, status=status.HTTP_404_NOT_FOUND)

        def in_scope(course_key):
            return any(
                s.institution == course_key.org and (not s.course_id or s.course_id == str(course_key)) for s in scopes
            )

        enrolments = [
            {"course_id": str(e.course_id), "mode": e.mode, "is_active": e.is_active, "created": e.created.isoformat()}
            for e in CourseEnrollment.objects.filter(user=learner) if in_scope(e.course_id)
        ]
        admissions = [
            {"course_id": str(a.course_key), "status": a.status, "institution": a.institution}
            for a in Admission.objects.filter(user=learner) if in_scope(a.course_key)
        ]
        if not enrolments and not admissions:
            # learner exists but has nothing in this officer's scope: indistinguishable from unknown
            return Response({"error": "not found"}, status=status.HTTP_404_NOT_FOUND)
        IdentityAudit.objects.create(
            user=learner, event="support_lookup", actor=request.user.username, detail="enrolment summary",
            identity_sub=identity.sub_for_user(learner) or "",
        )
        return Response({"username": learner.username, "enrolments": enrolments, "admissions": admissions})


COURSE_FIELDS = hooks.COURSE_METADATA_FIELDS


def _absolute_media_url(url):
    return url if url.startswith("http") else f"{settings.LMS_ROOT_URL}{url}"


def _serialize_course(course_key, org=None):
    """Course metadata from the product layer (``hooks.course_metadata``) with organisation fallbacks."""
    data = hooks.course_metadata(course_key)
    if org is not None:
        data.setdefault("institution_name", "")
        if not data["institution_name"]:
            data["institution_name"] = org.name
        if not data.get("institution_logo") and org.logo:
            data["institution_logo"] = _absolute_media_url(org.logo.url)
    data["course_id"] = str(course_key)
    return data


STUDIO_ROLES = {"staff", "instructor", "org_course_creator_group", "course_creator_group", "library_user"}
TEACH_ROLES = {"staff", "instructor", "limited_staff", "beta_testers", "data_researcher"}


class MeView(APIView):
    """Role-aware navigation facts for the caller; roles are those granted in the LMS, never claimed."""

    authentication_classes = (JwtAuthentication, SessionAuthentication)
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        from common.djangoapps.student.models import CourseAccessRole  # pylint: disable=import-outside-toplevel

        user = request.user
        access = list(CourseAccessRole.objects.filter(user=user).values_list("role", "org", "course_id"))
        roles = {r for r, _, _ in access}
        institutions = sorted({org for _, org, _ in access if org})
        creator = user.groups.filter(name=identity.COURSE_CREATOR_GROUP).exists()
        admin = bool(user.is_superuser or user.is_staff)
        studio = admin or creator or bool(roles & STUDIO_ROLES)
        teach = admin or bool(roles & TEACH_ROLES)
        console = bool(administered_institutions(user))
        return Response({
            "username": user.username,
            "name": user.profile.name if hasattr(user, "profile") else "",
            "email": user.email,
            "institutions": institutions,
            "doors": {"learn": True, "studio": studio, "teach": teach, "console": console, "admin": admin},
            "is_staff": studio or teach or admin,
        })


class DashboardApplicationsView(APIView):
    """The caller's own applications/admissions with catalogue metadata, for the My learning panel."""

    authentication_classes = (JwtAuthentication, SessionAuthentication)
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        from organizations.models import Organization  # pylint: disable=import-outside-toplevel

        admissions = list(Admission.objects.filter(user=request.user).order_by("-modified"))
        keys = [a.course_key for a in admissions]
        orgs = {o.short_name: o for o in Organization.objects.filter(short_name__in={k.org for k in keys})}
        items = []
        for adm in admissions:
            item = _serialize_course(adm.course_key, orgs.get(adm.course_key.org))
            item.update(
                application_id=adm.application_id,
                status=adm.status,
                status_label=adm.get_status_display(),
                modified=adm.modified.isoformat(),
            )
            items.append(item)
        return Response({"applications": items})


class DashboardCoursesView(APIView):
    """Listing metadata for the caller's own enrolments; anything else is not disclosed."""

    authentication_classes = (JwtAuthentication, SessionAuthentication)
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        from common.djangoapps.student.models import CourseEnrollment  # pylint: disable=import-outside-toplevel
        from organizations.models import Organization  # pylint: disable=import-outside-toplevel

        keys = [e.course_id for e in CourseEnrollment.enrollments_for_user(request.user)]
        orgs = {o.short_name: o for o in Organization.objects.filter(short_name__in={k.org for k in keys})}
        return Response({"courses": [_serialize_course(k, orgs.get(k.org)) for k in keys]})


class TenantHostCheckView(APIView):
    """
    Caddy on-demand TLS "ask" endpoint: 200 when `domain` is a known tenant host (eox-tenant Route),
    404 otherwise, so certificates are only issued for provisioned institutions.
    Anonymous by design; called by the reverse proxy on the internal network before the first TLS
    handshake for a new host.
    """

    authentication_classes = ()
    permission_classes = ()

    def get(self, request):
        from eox_tenant.models import Route  # pylint: disable=import-outside-toplevel

        domain = request.query_params.get("domain", "").lower().rstrip(".")
        if domain and Route.objects.filter(domain=domain).exists():
            return Response({"domain": domain, "tenant": True})
        return Response({"domain": domain, "tenant": False}, status=status.HTTP_404_NOT_FOUND)


class InstitutionsView(IntegrationView):
    """
    Control-plane provisioning of institutions (tenants).
    POST /campus/api/v1/institutions/  {"code": "UNIA", "name": "University of Abuja", "admin_email": "...", "meta": {...}}
      -> 200 {"code", "name", "host", "invitation_url"|null}; idempotent (re-running refreshes name/config).
    DELETE /campus/api/v1/institutions/?code=UNIA  -> 200; organisation inactive, host route removed, data kept.
    """

    def post(self, request):
        code = str(request.data.get("code") or "").strip().upper()
        name = str(request.data.get("name") or "").strip()
        admin_email = str(request.data.get("admin_email") or "").strip().lower() or None
        meta = request.data.get("meta") if isinstance(request.data.get("meta"), dict) else {}
        if not provisioning.CODE_RE.match(code) or code in provisioning.RESERVED_CODES:
            return Response({"error": "code must be 2-16 capital letters/digits and not reserved"}, status=status.HTTP_400_BAD_REQUEST)
        if not name:
            return Response({"error": "name is required"}, status=status.HTTP_400_BAD_REQUEST)
        tenant, invitation = provisioning.provision_institution(
            code, name, actor=request.user, admin_email=admin_email, meta=meta,
        )
        return Response({
            "code": code,
            "name": name,
            "host": provisioning.tenant_host(code, name),
            "tenant_id": tenant.pk,
            "invitation_url": f"{settings.LMS_ROOT_URL}/campus/invite/{invitation.token}/" if invitation else None,
        })

    def delete(self, request):
        code = str(request.query_params.get("code") or request.data.get("code") or "").strip().upper()
        if not code:
            return Response({"error": "code is required"}, status=status.HTTP_400_BAD_REQUEST)
        provisioning.deactivate_institution(code, actor=request.user)
        return Response({"code": code, "active": False})


class CredentialVerifyThrottle(AnonRateThrottle):
    rate = "60/hour"


class PublicCredentialView(APIView):
    """
    Public, unauthenticated credential check read by the product site's verify page: the institution
    awards and issues the credential, the platform records and verifies it. The identifier is the
    certificate's ``verify_uuid`` (printed on the certificate); the response carries only what
    the public certificate page already shows. 404 for unknown or never-issued identifiers.
    GET /campus/api/v1/credentials/<uuid>/
    """

    authentication_classes = ()
    permission_classes = ()
    throttle_classes = (CredentialVerifyThrottle,)

    def get(self, request, uuid):
        from lms.djangoapps.certificates.data import CertificateStatuses  # pylint: disable=import-outside-toplevel
        from lms.djangoapps.certificates.models import GeneratedCertificate  # pylint: disable=import-outside-toplevel
        from openedx.core.djangoapps.content.course_overviews.models import CourseOverview  # pylint: disable=import-outside-toplevel

        cert = GeneratedCertificate.objects.filter(verify_uuid=uuid.lower()).select_related("user").first()
        if cert is None or not cert.verify_uuid:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        if cert.status == CertificateStatuses.downloadable:
            state = "valid"
        elif cert.status in (CertificateStatuses.unavailable, CertificateStatuses.invalidated):
            state = "revoked"
        else:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        overview = CourseOverview.get_from_id(cert.course_id)
        listing = hooks.course_metadata(cert.course_id)
        institution = listing.get("institution_name") or cert.course_id.org
        return Response({
            "id": cert.verify_uuid,
            "status": state,
            "learner_name": cert.name or cert.user.profile.name,
            "course_id": str(cert.course_id),
            "course_title": overview.display_name,
            "institution": institution,
            "institution_code": cert.course_id.org,
            "programme_title": listing.get("programme_title", ""),
            "credential": listing.get("credential") or "Certificate",
            "issued_on": (cert.modified_date or cert.created_date).date().isoformat(),
            "certificate_url": f"{settings.LMS_ROOT_URL}/certificates/{cert.verify_uuid}",
        })


class EventsView(IntegrationView):
    """Reconciliation feed: every recorded event after ``since`` (sequence), oldest first."""

    def get(self, request):
        try:
            since = int(request.query_params.get("since", 0))
            limit = min(int(request.query_params.get("limit", 500)), 1000)
        except ValueError:
            return Response({"error": "since/limit must be integers"}, status=status.HTTP_400_BAD_REQUEST)
        rows = OutboxEvent.objects.filter(sequence__gt=since).order_by("sequence")[:limit]
        items = [{**events.serialize(e), "status": e.status} for e in rows]
        return Response({"events": items, "next_since": items[-1]["sequence"] if items else since})


class EventReplayView(IntegrationView):
    def post(self, request):
        ids = request.data.get("ids")
        if not isinstance(ids, list) or not ids or len(ids) > 200:
            return Response({"error": "ids must be a list of 1-200 event ids"}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"requeued": events.replay([str(i) for i in ids], actor=request.user)})
