"""
Integration API called by the EduLage control plane. Authenticated with an Open edX OAuth2/JWT
token for the ``edulage-integration`` service user, which must be a member of the
``EDULAGE_INTEGRATION_GROUP`` Django group (staff alone is not enough).

Learners are identified by the immutable EduLage user id (OIDC ``sub``). ``username`` /
``email`` are accepted for operator tooling but ``sub`` is the contract.

POST /edulage/api/v1/admissions/
  {"sub": "...", "course_id": "course-v1:ORG+CODE+RUN", "application_id": "APP-1",
   "institution": "ORG", "action": "submit" | "review" | "admit" | "decline" | "withdraw" | "defer"}
  -> 200 applied (learner has an LMS account, enrolment synced)
  -> 202 pending (no LMS account yet; applied automatically at first SSO login)
GET  /edulage/api/v1/admissions/?sub=...&course_id=...

PUT  /edulage/api/v1/roles/      {"sub": "...", "roles": ["instructor:course-v1:...", ...]}
  Synchronises detailed (per course run) entitlements; reconciles only API-sourced grants.
POST /edulage/api/v1/users/status/   {"sub": "...", "status": "suspended" | "active", "reason": "..."}
  Immediate suspension: sessions, tokens and roles revoked; 403 on every request thereafter.

GET  /edulage/api/v1/support/learners/?username=...   (OEC support officer, session auth)
  Enrolment/progress summary for a learner, limited to the officer's SupportScope.

PUT  /edulage/api/v1/listings/   {"listings": [{"course_id": "...", "institution": "ORG", "institution_name": "...",
  "classification": "degree", "credential": "MSc", "programme_title": "...", ...}]}
  Presentation metadata from the EduLage catalogue for course runs (upsert, idempotent).
GET  /edulage/api/v1/dashboard/courses/   (learner, session auth)
  Listing metadata for the caller's own enrolments, used by the "My learning" cards.
GET  /edulage/api/v1/dashboard/applications/   (learner, session auth)
  The caller's applications/admissions with status, for the "Applications" panel.
GET  /edulage/api/v1/me/   (session auth; 401 when anonymous)
  Who the caller is and which "doors" to show: learner always, ``studio``/``teach`` for institution
  staff (from CourseAccessRole), ``console`` for institution administrators, ``admin`` for EduLage admins. Used by the edulage.org header/sign-in
  page and the LMS/Studio header so navigation is role-aware without anyone self-declaring a role.
GET  /edulage/api/v1/runs/?course_id=...   (public)
  Enrolment policy (admission / open_free / open_paid) and price per run, for edulage.org CTAs.

POST/PUT are idempotent: repeating a call converges on the same state, so EduLage may retry on
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
from rest_framework.views import APIView

from .. import identity
from ..console import administered_institutions
from ..models import Admission, CourseListing, IdentityAudit, ManagedRole, SupportScope

User = get_user_model()

ACTION_TO_STATUS = {
    "submit": Admission.STATUS_SUBMITTED,
    "review": Admission.STATUS_UNDER_REVIEW,
    "admit": Admission.STATUS_ADMITTED,
    "decline": Admission.STATUS_DECLINED,
    "withdraw": Admission.STATUS_WITHDRAWN,
    "defer": Admission.STATUS_DEFERRED,
}


class IsEdulageIntegration(BasePermission):
    """Staff service user in the integration group (institutions never call these endpoints)."""

    def has_permission(self, request, view):
        u = request.user
        return bool(
            u and u.is_authenticated and u.is_active and u.is_staff
            and u.groups.filter(name=settings.EDULAGE_INTEGRATION_GROUP).exists()
        )


class IntegrationView(APIView):
    authentication_classes = (JwtAuthentication, SessionAuthenticationAllowInactiveUser)
    permission_classes = (IsEdulageIntegration,)

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
        return user, identity.sub_for_user(user), None


def _serialize(adm):
    return {
        "sub": adm.edulage_sub,
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
            qs = qs.filter(edulage_sub=sub)
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
                adm, _ = Admission.objects.update_or_create(user=user, course_key=course_key, defaults={**defaults, "edulage_sub": sub})
            else:
                adm, _ = Admission.objects.update_or_create(edulage_sub=sub, course_key=course_key, user=None, defaults=defaults)
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
        if "edulage_admin" in roles:
            return Response({"error": "edulage_admin is only granted via the login claim"}, status=status.HTTP_400_BAD_REQUEST)
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
        if not enrolments:
            # learner exists but has nothing in this officer's scope: indistinguishable from unknown
            return Response({"error": "not found"}, status=status.HTTP_404_NOT_FOUND)
        admissions = [
            {"course_id": str(a.course_key), "status": a.status, "institution": a.institution}
            for a in Admission.objects.filter(user=learner) if in_scope(a.course_key)
        ]
        IdentityAudit.objects.create(
            user=learner, event="support_lookup", actor=request.user.username, detail="enrolment summary",
            edulage_sub=identity.sub_for_user(learner) or "",
        )
        return Response({"username": learner.username, "enrolments": enrolments, "admissions": admissions})


LISTING_FIELDS = (
    "institution", "institution_name", "institution_logo", "institution_url", "programme_title", "programme_url",
    "classification", "credential", "delivery_mode", "enrolment_policy", "price", "currency",
)
PUBLIC_RUN_FIELDS = ("course_id", "enrolment_policy", "price", "currency", "institution", "institution_name", "classification")


def _absolute_media_url(url):
    return url if url.startswith("http") else f"{settings.LMS_ROOT_URL}{url}"


def _serialize_listing(course_key, listing, org=None):
    if listing is not None:
        data = listing.as_dict()
    else:
        data = {f: "" for f in LISTING_FIELDS}
        data.update(
            enrolment_policy=CourseListing.POLICY_ADMISSION,
            price="0.00",
            currency="NGN",
            institution=course_key.org,
            institution_name=(org.name if org else course_key.org),
            institution_logo=_absolute_media_url(org.logo.url) if org and org.logo else "",
            classification="",
            classification_label="Course",
        )
    data["course_id"] = str(course_key)
    return data


class ListingsView(IntegrationView):
    def put(self, request):
        items = request.data.get("listings")
        if not isinstance(items, list):
            return Response({"error": "listings must be a list"}, status=status.HTTP_400_BAD_REQUEST)
        valid = {c for c, _ in CourseListing.CLASSIFICATIONS}
        parsed = []
        for item in items:
            if not isinstance(item, dict):
                return Response({"error": "each listing must be an object"}, status=status.HTTP_400_BAD_REQUEST)
            try:
                course_key = CourseKey.from_string(item["course_id"])
            except (KeyError, TypeError, InvalidKeyError):
                return Response({"error": "course_id is required and must be valid"}, status=status.HTTP_400_BAD_REQUEST)
            if item.get("classification", "short") not in valid:
                return Response({"error": f"unknown classification for {course_key}"}, status=status.HTTP_400_BAD_REQUEST)
            if item.get("enrolment_policy", CourseListing.POLICY_ADMISSION) not in {p for p, _ in CourseListing.POLICIES}:
                return Response({"error": f"unknown enrolment_policy for {course_key}"}, status=status.HTTP_400_BAD_REQUEST)
            defaults = {f: item[f] for f in LISTING_FIELDS if f in item}
            defaults.setdefault("institution", course_key.org)
            defaults.setdefault("institution_name", course_key.org)
            parsed.append((course_key, defaults))
        result = []
        with transaction.atomic():
            for course_key, defaults in parsed:
                listing, _ = CourseListing.objects.update_or_create(course_key=course_key, defaults=defaults)
                result.append(_serialize_listing(course_key, listing))
        return Response({"listings": result})


class PublicRunsView(APIView):
    """
    Public, unauthenticated: enrolment policy and price for course runs, read by edulage.org
    programme pages to render "Enrol now" / "Enrol now — ₦X" / "Apply".
    GET /edulage/api/v1/runs/?course_id=...&course_id=...   (max 50)
    """

    authentication_classes = ()
    permission_classes = ()

    def get(self, request):
        keys = []
        for raw in request.query_params.getlist("course_id")[:50]:
            try:
                keys.append(CourseKey.from_string(raw))
            except InvalidKeyError:
                continue
        listings = {l.course_key: l for l in CourseListing.objects.filter(course_key__in=keys)}
        runs = []
        for k in keys:
            data = _serialize_listing(k, listings.get(k))
            runs.append({f: data[f] for f in PUBLIC_RUN_FIELDS})
        return Response({"runs": runs})


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
        listings = {l.course_key: l for l in CourseListing.objects.filter(course_key__in=keys)}
        orgs = {o.short_name: o for o in Organization.objects.filter(short_name__in={k.org for k in keys})}
        items = []
        for adm in admissions:
            item = _serialize_listing(adm.course_key, listings.get(adm.course_key), orgs.get(adm.course_key.org))
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
        listings = {l.course_key: l for l in CourseListing.objects.filter(course_key__in=keys)}
        orgs = {o.short_name: o for o in Organization.objects.filter(short_name__in={k.org for k in keys})}
        return Response({"courses": [_serialize_listing(k, listings.get(k), orgs.get(k.org)) for k in keys]})
