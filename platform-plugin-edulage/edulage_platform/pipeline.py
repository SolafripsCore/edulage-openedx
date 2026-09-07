"""
python-social-auth pipeline step: project EduLage role claims onto Open edX access roles.

Claim format (``edulage_roles`` in the ID token / userinfo):

    edulage_admin                       -> Django is_staff + GlobalStaff
    oec_support                         -> SupportStaffRole (learner support, no academic authority)
    institution_admin:<ORG>             -> OrgStaffRole + OrgInstructorRole + OrgContentCreatorRole
    programme_admin:<ORG>               -> OrgStaffRole      (Open edX has no programme scope; see report)
    course_author:<ORG>                 -> OrgContentCreatorRole (+ CourseCreator row for Studio)
    trainer:<ORG>                       -> OrgContentCreatorRole
    instructor:<course-v1:...>          -> CourseInstructorRole
    teaching_assistant:<course-v1:...>  -> CourseLimitedStaffRole
    learner                             -> no role (access comes from enrolment only)

Roles managed by this step are reconciled on every login: anything previously granted by
EduLage that is no longer claimed is revoked, so suspending an institution admin in EduLage
takes effect at their next SSO. Roles granted directly in Open edX by other means are not
touched.
"""
import logging

from django.contrib.auth.models import Group
from opaque_keys import InvalidKeyError
from opaque_keys.edx.keys import CourseKey

from .models import ManagedRole

log = logging.getLogger(__name__)

EDULAGE_BACKEND = "edulage"

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


def _desired_roles(claims):
    """Return {(role, org, course_id)} derived from claim strings."""
    desired = set()
    for claim in claims:
        name, _, scope = claim.partition(":")
        if name in ORG_ROLES and scope:
            for role in ORG_ROLES[name]:
                desired.add((role, scope, ""))
        elif name in COURSE_ROLES and scope:
            try:
                key = CourseKey.from_string(scope)
            except InvalidKeyError:
                log.warning("edulage: ignoring role claim with invalid course key %r", claim)
                continue
            desired.add((COURSE_ROLES[name], key.org, str(key)))
        elif name == "oec_support":
            desired.add(("support", "", ""))
    return desired


def _access_role_kwargs(user, role, org, course_id):
    kwargs = {"user": user, "role": role, "org": org}
    if course_id:
        kwargs["course_id"] = CourseKey.from_string(course_id)
    return kwargs


def sync_edulage_roles(backend, user=None, response=None, *args, **kwargs):  # pylint: disable=unused-argument
    if backend.name != EDULAGE_BACKEND or user is None or response is None:
        return {}
    from common.djangoapps.student.models import CourseAccessRole  # pylint: disable=import-outside-toplevel

    claims = response.get("edulage_roles", [])
    desired = _desired_roles(claims)

    is_admin = "edulage_admin" in claims
    if user.is_staff != is_admin and not user.is_superuser:
        user.is_staff = is_admin
        user.save(update_fields=["is_staff"])

    current = {(m.role, m.org, m.course_id): m for m in ManagedRole.objects.filter(user=user)}
    for key, managed in current.items():
        if key not in desired:
            role, org, course_id = key
            CourseAccessRole.objects.filter(**_access_role_kwargs(user, role, org, course_id)).delete()
            managed.delete()
            log.info("edulage: revoked %s for %s (%s %s)", role, user.username, org, course_id)
    for role, org, course_id in desired - set(current):
        CourseAccessRole.objects.get_or_create(**_access_role_kwargs(user, role, org, course_id))
        ManagedRole.objects.create(user=user, role=role, org=org, course_id=course_id)
        log.info("edulage: granted %s to %s (%s %s)", role, user.username, org, course_id)

    if any(r[0] == "org_course_creator_group" for r in desired):
        _grant_course_creator(user)
    return {}


def _grant_course_creator(user):
    """Studio only lets members of the course-creator group create courses (per-org via CourseAccessRole)."""
    group, _ = Group.objects.get_or_create(name="course_creator_group")
    user.groups.add(group)
