"""
Identity operations shared by the SSO pipeline and the control-plane API: resolving an
control-plane user id (OIDC ``sub``) to an Open edX user, projecting role claims onto Open
edX access roles, applying pending admissions, and suspending/reactivating accounts.

Role claim format (compact; issued in the ID token or pushed through the roles API):

    platform_admin                       -> Django is_staff + GlobalStaff
    platform_support:<ORG>                   -> SupportScope(ORG)           (scoped, read-only; no Open edX role)
    institution_admin:<ORG>             -> OrgStaffRole + OrgInstructorRole + OrgContentCreatorRole
    programme_admin:<ORG>               -> OrgStaffRole                (Open edX has no programme scope)
    course_author:<ORG>                 -> OrgContentCreatorRole (+ course_creator_group for Studio)
    trainer:<ORG>                       -> OrgContentCreatorRole
    instructor:<course-v1:...>          -> CourseInstructorRole
    teaching_assistant:<course-v1:...>  -> CourseLimitedStaffRole
    learner                             -> no role (access comes from enrolment only)

Tokens should carry only global and institution-level claims; per-course-run entitlements
are synchronised by the control plane through ``PUT /campus/api/v1/roles/`` (source ``api``) so ID
tokens stay small. Each source reconciles only the grants it made.
"""
import logging
import secrets

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import transaction
from opaque_keys import InvalidKeyError
from opaque_keys.edx.keys import CourseKey

from .models import Admission, IdentityAudit, ManagedRole, SupportScope

log = logging.getLogger(__name__)
User = get_user_model()

CAMPUS_BACKEND = "campus"
COURSE_CREATOR_GROUP = "course_creator_group"

ORG_ROLES = {
    "institution_admin": ("staff", "instructor", "org_course_creator_group"),
    "programme_admin": ("staff",),
    "course_author": ("org_course_creator_group",),
    "trainer": ("org_course_creator_group",),
}
COURSE_ROLES = {
    "instructor": "instructor",
    "teaching_assistant": "limited_staff",
}
STAFF_CLAIMS = set(ORG_ROLES) | set(COURSE_ROLES) | {"platform_admin", "platform_support"}


def audit(event, user=None, sub="", email="", detail="", actor="sso"):
    IdentityAudit.objects.create(user=user, identity_sub=sub or "", email=email or "", event=event, detail=detail, actor=actor)


def user_for_sub(sub):
    """Open edX user linked to this control-plane identity, or None."""
    from social_django.models import UserSocialAuth  # pylint: disable=import-outside-toplevel

    link = UserSocialAuth.objects.filter(provider=CAMPUS_BACKEND, uid=sub).select_related("user").first()
    return link.user if link else None


def sub_for_user(user):
    from social_django.models import UserSocialAuth  # pylint: disable=import-outside-toplevel

    link = UserSocialAuth.objects.filter(provider=CAMPUS_BACKEND, user=user).first()
    return link.uid if link else None


def parse_claims(claims):
    """Return ({(role, org, course_id)}, {(institution, course_id)}) from claim strings."""
    roles, support = set(), set()
    for claim in claims:
        name, _, scope = claim.partition(":")
        if name in ORG_ROLES and scope:
            for role in ORG_ROLES[name]:
                roles.add((role, scope, ""))
        elif name in COURSE_ROLES and scope:
            try:
                key = CourseKey.from_string(scope)
            except InvalidKeyError:
                log.warning("campus: ignoring role claim with invalid course key %r", claim)
                continue
            roles.add((COURSE_ROLES[name], key.org, str(key)))
        elif name == "platform_support":
            if scope:
                support.add((scope, ""))
            else:
                log.warning("campus: ignoring unscoped platform_support claim (institution required)")
    return roles, support


def is_staff_claimset(claims):
    return any(c.partition(":")[0] in STAFF_CLAIMS for c in claims)


def _access_role_kwargs(user, role, org, course_id):
    kwargs = {"user": user, "role": role, "org": org}
    if course_id:
        kwargs["course_id"] = CourseKey.from_string(course_id)
    return kwargs


@transaction.atomic
def apply_roles(user, claims, source, actor="sso"):
    """Grant/revoke Open edX roles for ``user`` so that grants from ``source`` equal ``claims``."""
    from common.djangoapps.student.models import CourseAccessRole  # pylint: disable=import-outside-toplevel

    desired, support = parse_claims(claims)

    if source == ManagedRole.SOURCE_TOKEN:
        is_admin = "platform_admin" in claims
        if user.is_staff != is_admin and not user.is_superuser:
            user.is_staff = is_admin
            user.save(update_fields=["is_staff"])

    current = {(m.role, m.org, m.course_id): m for m in ManagedRole.objects.filter(user=user, source=source)}
    for key, managed in current.items():
        if key not in desired:
            role, org, course_id = key
            CourseAccessRole.objects.filter(**_access_role_kwargs(user, role, org, course_id)).delete()
            managed.delete()
            log.info("campus: revoked %s for %s (%s %s)", role, user.username, org, course_id)
    for role, org, course_id in desired - set(current):
        CourseAccessRole.objects.get_or_create(**_access_role_kwargs(user, role, org, course_id))
        ManagedRole.objects.create(user=user, role=role, org=org, course_id=course_id, source=source)
        log.info("campus: granted %s to %s (%s %s)", role, user.username, org, course_id)

    current_support = {(s.institution, s.course_id): s for s in SupportScope.objects.filter(user=user, source=source)}
    for key, scope in current_support.items():
        if key not in support:
            scope.delete()
    for institution, course_id in support - set(current_support):
        SupportScope.objects.create(user=user, institution=institution, course_id=course_id, source=source)

    group, _ = Group.objects.get_or_create(name=COURSE_CREATOR_GROUP)
    if ManagedRole.objects.filter(user=user, role="org_course_creator_group").exists():
        user.groups.add(group)
    else:
        user.groups.remove(group)

    audit("roles_synced", user=user, sub=sub_for_user(user), detail=f"{source}: {sorted(claims)}", actor=actor)
    return desired, support


def revoke_all_roles(user, actor):
    """Remove every control-plane-managed grant (both sources) and Django staff flag."""
    from common.djangoapps.student.models import CourseAccessRole  # pylint: disable=import-outside-toplevel

    for managed in ManagedRole.objects.filter(user=user):
        CourseAccessRole.objects.filter(**_access_role_kwargs(user, managed.role, managed.org, managed.course_id)).delete()
    ManagedRole.objects.filter(user=user).delete()
    SupportScope.objects.filter(user=user).delete()
    group = Group.objects.filter(name=COURSE_CREATOR_GROUP).first()
    if group:
        user.groups.remove(group)
    if user.is_staff and not user.is_superuser:
        user.is_staff = False
        user.save(update_fields=["is_staff"])
    log.info("campus: revoked all managed roles for %s (%s)", user.username, actor)


def sync_enrolment(adm):
    """Make the Open edX enrolment match the admission status (no-op for pending admissions)."""
    from common.djangoapps.student.models import CourseEnrollment  # pylint: disable=import-outside-toplevel

    if adm.is_pending:
        return
    if adm.is_active:
        if not adm.user.is_active:
            return
        CourseEnrollment.enroll(adm.user, adm.course_key, mode=adm.mode, check_access=False)
    elif CourseEnrollment.is_enrolled(adm.user, adm.course_key):
        CourseEnrollment.unenroll(adm.user, adm.course_key)


@transaction.atomic
def apply_pending_admissions(user, sub):
    """Attach admissions recorded for ``sub`` before the learner had an LMS account, and enrol."""
    pending = list(Admission.objects.filter(identity_sub=sub, user__isnull=True))
    for adm in pending:
        if Admission.objects.filter(user=user, course_key=adm.course_key).exclude(pk=adm.pk).exists():
            # a username-keyed record already exists for this run; the sub-keyed one wins
            Admission.objects.filter(user=user, course_key=adm.course_key).exclude(pk=adm.pk).delete()
        adm.user = user
        adm.save(update_fields=["user", "modified"])
        sync_enrolment(adm)
        audit("admission_applied", user=user, sub=sub, detail=f"{adm.course_key} {adm.status}")
    # back-fill the sub on records created by username/email before the identity was linked
    Admission.objects.filter(user=user, identity_sub__isnull=True).update(identity_sub=sub)
    return len(pending)


@transaction.atomic
def set_account_status(user, active, actor, reason=""):
    """
    Suspend (``active=False``) or reactivate an account with immediate effect.

    Suspension: ``is_active=False`` (blocks password/OIDC login and the admissions API),
    ``UserStanding.ACCOUNT_DISABLED`` (UserStandingMiddleware returns 403 on every request of
    every existing session, whatever the session backend), password rotation (invalidates the
    Django session auth hash so cached sessions die), OAuth2 access/refresh tokens deleted
    (Studio, MFEs, API clients), and every control-plane-managed role revoked. Course enrolments are
    left in place so reactivation restores learning without re-admission.
    """
    from common.djangoapps.student.models import UserStanding  # pylint: disable=import-outside-toplevel
    from oauth2_provider.models import AccessToken, RefreshToken  # pylint: disable=import-outside-toplevel

    sub = sub_for_user(user)
    if active:
        user.is_active = True
        user.save(update_fields=["is_active"])
        UserStanding.objects.filter(user=user).update(account_status=UserStanding.ACCOUNT_ENABLED)
        audit("reactivated", user=user, sub=sub, detail=reason, actor=actor)
        return

    user.is_active = False
    user.set_password(secrets.token_urlsafe(32))
    user.save(update_fields=["is_active", "password"])
    standing, _ = UserStanding.objects.get_or_create(
        user=user, defaults={"account_status": UserStanding.ACCOUNT_DISABLED, "changed_by": User.objects.get(username=actor)}
    )
    if standing.account_status != UserStanding.ACCOUNT_DISABLED:
        standing.account_status = UserStanding.ACCOUNT_DISABLED
        standing.save(update_fields=["account_status", "standing_last_changed_at"])
    AccessToken.objects.filter(user=user).delete()
    RefreshToken.objects.filter(user=user).delete()
    revoke_all_roles(user, actor)
    audit("suspended", user=user, sub=sub, detail=reason, actor=actor)
