"""
Studio (CMS only): mirror the control plane's ``org_course_creator_group`` grants into the
``CourseCreator`` table so the Studio home "New course" form offers exactly the institution(s)
the author may create runs for (``ENABLE_CREATOR_GROUP`` reads that table, not the access role).

A platform-wide creator granted by an operator in Django admin (``all_organizations`` + granted) is
left alone; everything else (including the ``unrequested`` row Studio creates on first visit) is
reconciled against the managed grants.

The ``organizations`` M2M is written through its through-table: the stock ``m2m_changed`` handler
re-applies ``OrgContentCreatorRole`` on behalf of ``instance.admin`` and requires global staff,
whereas here the access role is already maintained by ``identity.apply_roles``.
"""
import logging

from django.core.exceptions import PermissionDenied

from .models import ManagedRole

log = logging.getLogger(__name__)

ORG_CREATOR_ROLE = "org_course_creator_group"
SYNCED_SESSION_KEY = "campus_creator_synced"


def sync_course_creator(user):
    from cms.djangoapps.course_creators.models import CourseCreator  # pylint: disable=import-outside-toplevel
    from organizations.models import Organization  # pylint: disable=import-outside-toplevel

    orgs = sorted(set(ManagedRole.objects.filter(user=user, role=ORG_CREATOR_ROLE).values_list("org", flat=True)))
    creator = CourseCreator.objects.filter(user=user).first()
    if creator is not None and creator.all_organizations and creator.state == CourseCreator.GRANTED:
        return
    through = CourseCreator.organizations.through
    if not orgs:
        if creator is not None and creator.state == CourseCreator.GRANTED:
            creator.admin = user
            creator.state = CourseCreator.UNREQUESTED
            creator.save()
            through.objects.filter(coursecreator=creator).delete()
            log.info("campus: studio course-creator revoked for %s", user.username)
        return
    if creator is None:
        creator = CourseCreator(user=user, all_organizations=False)
    creator.admin = user
    creator.all_organizations = False
    creator.state = CourseCreator.GRANTED
    creator.save()
    wanted = {o.id for o in Organization.objects.filter(short_name__in=orgs)}
    current = set(through.objects.filter(coursecreator=creator).values_list("organization_id", flat=True))
    through.objects.filter(coursecreator=creator, organization_id__in=current - wanted).delete()
    through.objects.bulk_create([through(coursecreator=creator, organization_id=oid) for oid in wanted - current])
    log.info("campus: studio course-creator for %s scoped to %s", user.username, orgs)


def sync_once_per_session(request):
    """Studio authenticates from the LMS session cookie (no login signal), so reconcile per session."""
    if not request.user.is_authenticated or request.session.get(SYNCED_SESSION_KEY):
        return
    request.session[SYNCED_SESSION_KEY] = True
    try:
        sync_course_creator(request.user)
    except PermissionDenied:
        log.warning("campus: could not reconcile studio course-creator for %s", request.user.username)
