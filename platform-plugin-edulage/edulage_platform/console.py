"""
Institution console — ``/edulage/institution/``: where an institution administrator sees who
holds staff roles at their institution, invites tutors/authors/administrators by e-mail, and
revokes access. EduLage administrators see every institution.

Roles are never self-declared. An invitation names an e-mail, a role and (for instructor / TA)
a course run; the invitee signs in (or creates an account) with that e-mail and accepts from
``/edulage/invite/<token>/``. Acceptance appends the claim to the account's ``edulage_roles``
on the identity provider (which also switches on mandatory MFA through the ``edulage-staff``
group) and mirrors it onto Open edX immediately through ``identity.apply_roles`` — the same
path the sign-in pipeline uses, so the next login reproduces exactly the same grants.
"""
import logging
import secrets
from collections import defaultdict
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.db import transaction
from django.http import Http404, HttpResponseForbidden, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST
from opaque_keys import InvalidKeyError
from opaque_keys.edx.keys import CourseKey

from . import admissions, emails, identity, keycloak
from .auth import REGISTER_PARAM
from .middleware import STAFF_SESSION_KEY
from .models import ManagedRole, StaffInvitation

log = logging.getLogger(__name__)

CONSOLE_PATH = "/edulage/institution/"
ROLE_LABELS = dict(StaffInvitation.ROLE_CHOICES)


def _login_redirect(request, register=False):
    query = {"auth_entry": "login", "next": request.get_full_path()}
    if register:
        query[REGISTER_PARAM] = "1"
    return HttpResponseRedirect(f"/auth/login/edulage/?{urlencode(query)}")


def _page_context(request, **extra):
    return {
        "site_url": settings.EDULAGE_SITE_URL,
        "brand_url": settings.EDULAGE_BRAND_URL,
        "studio_url": f"{settings.EDULAGE_STUDIO_URL.rstrip('/')}/home" if settings.EDULAGE_STUDIO_URL else "",
        "platform_name": getattr(settings, "PLATFORM_NAME", "EduLage"),
        "support_email": getattr(settings, "CONTACT_EMAIL", ""),
        "console_url": CONSOLE_PATH,
        "expiry_days": StaffInvitation.EXPIRY_DAYS,
        **extra,
    }


def administered_institutions(user):
    """Org short names the user administers: all for EduLage admins, else institution_admin grants."""
    from organizations.models import Organization  # pylint: disable=import-outside-toplevel

    if user.is_superuser or user.is_staff:
        return sorted(Organization.objects.filter(active=True).values_list("short_name", flat=True))
    creator = set(ManagedRole.objects.filter(user=user, role="org_course_creator_group", course_id="").values_list("org", flat=True))
    staff = set(ManagedRole.objects.filter(user=user, role="staff", course_id="").values_list("org", flat=True))
    return sorted(creator & staff)


def _org_name(org):
    from organizations.models import Organization  # pylint: disable=import-outside-toplevel

    o = Organization.objects.filter(short_name=org).first()
    # eox-tenant forces Organization.name == short_name; the display name is kept in ``description``.
    return (o.description or o.name) if o else org


def _course_runs(org):
    from openedx.core.djangoapps.content.course_overviews.models import CourseOverview  # pylint: disable=import-outside-toplevel

    return [(str(c.id), c.display_name) for c in CourseOverview.objects.filter(org=org).order_by("display_name")]


def _describe(roles):
    """Human labels for a member's Open edX grants at one institution (reverse of identity.ORG_ROLES)."""
    org_level = {r for r, c in roles if not c}
    labels = []
    if {"staff", "instructor", "org_course_creator_group"} <= org_level:
        labels.append(ROLE_LABELS["institution_admin"])
    elif "staff" in org_level:
        labels.append(ROLE_LABELS["programme_admin"])
    if "org_course_creator_group" in org_level and ROLE_LABELS["institution_admin"] not in labels:
        labels.append(ROLE_LABELS["course_author"])
    for r, c in sorted(roles):
        if c and r == "instructor":
            labels.append(f"Instructor · {c.split('+')[-1] if '+' in c else c}")
        elif c and r == "limited_staff":
            labels.append(f"Teaching assistant · {c.split('+')[-1] if '+' in c else c}")
    return labels


def _members(org):
    grants = defaultdict(set)
    for m in ManagedRole.objects.filter(org=org).select_related("user"):
        grants[m.user].add((m.role, m.course_id))
    members = []
    for user, roles in grants.items():
        members.append({
            "username": user.username,
            "name": (user.profile.name if hasattr(user, "profile") else "") or user.username,
            "email": user.email,
            "roles": _describe(roles),
            "active": user.is_active,
        })
    return sorted(members, key=lambda m: m["name"].lower())


@never_cache
def console_view(request, org=None):
    if not request.user.is_authenticated:
        return _login_redirect(request)
    institutions = administered_institutions(request.user)
    if not institutions:
        return render(request, "edulage_platform/console_denied.html", _page_context(request), status=403)
    if org is None:
        return redirect("edulage:console-org", org=institutions[0])
    if org not in institutions:
        return HttpResponseForbidden("Not an administrator of this institution")
    invitations = StaffInvitation.objects.filter(institution=org, accepted__isnull=True, revoked__isnull=True)
    pending = [i for i in invitations if i.state == "pending"]
    context = _page_context(
        request,
        org=org,
        org_name=_org_name(org),
        institutions=[(o, _org_name(o)) for o in institutions],
        members=_members(org),
        invitations=pending,
        org_roles=StaffInvitation.ORG_ROLES,
        course_roles=StaffInvitation.COURSE_ROLES,
        course_runs=_course_runs(org),
        applications=admissions.applications(org),
        idp_ready=keycloak.configured(),
        me=request.user.username,
    )
    return render(request, "edulage_platform/console.html", context)


def _guard(request, org):
    if not request.user.is_authenticated:
        return _login_redirect(request)
    if org not in administered_institutions(request.user):
        return HttpResponseForbidden("Not an administrator of this institution")
    return None


@never_cache
@require_POST
def invite_view(request, org):
    refused = _guard(request, org)
    if refused:
        return refused
    email = (request.POST.get("email") or "").strip().lower()
    role = request.POST.get("role") or ""
    course_id = (request.POST.get("course_id") or "").strip()
    back = redirect("edulage:console-org", org=org)

    if "@" not in email or role not in ROLE_LABELS:
        messages.error(request, "Enter a valid e-mail address and choose a role.")
        return back
    if role in dict(StaffInvitation.COURSE_ROLES):
        try:
            if CourseKey.from_string(course_id).org != org:
                raise InvalidKeyError(CourseKey, course_id)
        except InvalidKeyError:
            messages.error(request, "Instructor and teaching-assistant roles need one of this institution's course runs.")
            return back
    else:
        course_id = ""
    if not keycloak.configured():
        messages.error(request, "Staff invitations are not enabled on this environment (identity provider not configured).")
        return back
    if StaffInvitation.objects.filter(email=email, institution=org, role=role, course_id=course_id, accepted__isnull=True, revoked__isnull=True).exists():
        messages.info(request, f"{email} already has a pending invitation for that role.")
        return back

    invitation = StaffInvitation.objects.create(
        token=secrets.token_urlsafe(32), email=email, institution=org, role=role, course_id=course_id, invited_by=request.user,
    )
    identity.audit("invited", user=request.user, email=email, detail=f"{invitation.claim} by {request.user.username}", actor="console")
    if emails.send_staff_invitation(invitation, _org_name(org), request.build_absolute_uri(f"/edulage/invite/{invitation.token}/")):
        messages.success(request, f"Invitation sent to {email} ({invitation.role_label}).")
    else:
        messages.warning(request, f"Invitation for {email} recorded, but the e-mail could not be sent; share the link from the list below.")
    return back


@never_cache
@require_POST
def revoke_invitation_view(request, org, pk):
    refused = _guard(request, org)
    if refused:
        return refused
    invitation = get_object_or_404(StaffInvitation, pk=pk, institution=org, accepted__isnull=True)
    invitation.revoked = timezone.now()
    invitation.save(update_fields=["revoked"])
    identity.audit("invite_revoked", user=request.user, email=invitation.email, detail=invitation.claim, actor="console")
    messages.success(request, f"Invitation for {invitation.email} withdrawn.")
    return redirect("edulage:console-org", org=org)


def _claim_in_org(claim, org):
    name, _, scope = claim.partition(":")
    if name in identity.ORG_ROLES or name == "oec_support":
        return scope == org
    if name in identity.COURSE_ROLES:
        try:
            return CourseKey.from_string(scope).org == org
        except InvalidKeyError:
            return False
    return False


def _sync_idp_roles(user, mutate, actor):
    """Read the account's roles on the IdP, apply ``mutate(roles) -> roles``, write back and mirror onto the LMS."""
    sub = identity.sub_for_user(user)
    kc_user = keycloak.get_user(sub) if sub else keycloak.find_user_by_email(user.email)
    if kc_user is None:
        raise keycloak.KeycloakError("account not found on the identity provider")
    roles = keycloak.set_roles(kc_user, mutate(keycloak.roles_of(kc_user)))
    identity.apply_roles(user, roles, ManagedRole.SOURCE_TOKEN, actor=actor)
    return roles


@never_cache
@require_POST
def revoke_member_view(request, org, username):
    from django.contrib.auth import get_user_model  # pylint: disable=import-outside-toplevel

    refused = _guard(request, org)
    if refused:
        return refused
    back = redirect("edulage:console-org", org=org)
    if username == request.user.username:
        messages.error(request, "You cannot remove your own access; ask another administrator or EduLage support.")
        return back
    user = get_object_or_404(get_user_model(), username=username)
    if not ManagedRole.objects.filter(user=user, org=org).exists():
        raise Http404
    try:
        _sync_idp_roles(user, lambda roles: [r for r in roles if not _claim_in_org(r, org)], actor=f"console:{request.user.username}")
    except keycloak.KeycloakError as exc:
        log.warning("edulage: revoke for %s at %s failed: %s", username, org, exc)
        messages.error(request, f"Could not update the identity provider ({exc}); no change made.")
        return back
    messages.success(request, f"{user.email or username} no longer holds staff roles at {org}.")
    return back


@never_cache
def invite_accept_view(request, token):
    invitation = StaffInvitation.objects.filter(token=token).first()
    if invitation is None:
        raise Http404
    org_name = _org_name(invitation.institution)
    context = _page_context(request, invitation=invitation, org_name=org_name)

    if invitation.state != "pending":
        return render(request, "edulage_platform/invite.html", {**context, "outcome": invitation.state}, status=410)

    if not request.user.is_authenticated:
        if request.GET.get("go") == "register":
            return _login_redirect(request, register=True)
        if request.GET.get("go") == "signin":
            return _login_redirect(request)
        return render(request, "edulage_platform/invite.html", {**context, "outcome": "anonymous"})

    if (request.user.email or "").lower() != invitation.email.lower():
        return render(request, "edulage_platform/invite.html", {**context, "outcome": "wrong-account", "account_email": request.user.email}, status=403)

    if request.method != "POST":
        return render(request, "edulage_platform/invite.html", {**context, "outcome": "confirm"})

    # IdP first (set_roles is idempotent, so a retry after a DB hiccup is harmless), then record acceptance.
    try:
        _sync_idp_roles(request.user, lambda roles: roles + [invitation.claim], actor=f"console:{invitation.invited_by_id}")
    except keycloak.KeycloakError as exc:
        log.warning("edulage: accepting invitation %s failed: %s", invitation.pk, exc)
        return render(request, "edulage_platform/invite.html", {**context, "outcome": "failed"}, status=503)
    with transaction.atomic():
        invitation.accepted = timezone.now()
        invitation.accepted_by = request.user
        invitation.save(update_fields=["accepted", "accepted_by"])
        identity.audit("invite_accepted", user=request.user, email=invitation.email, detail=invitation.claim, actor="console")
    request.session[STAFF_SESSION_KEY] = True
    return render(request, "edulage_platform/invite.html", {**context, "outcome": "accepted"})
