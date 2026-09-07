import logging

from django.conf import settings
from django.db.models import Q
from opaque_keys.edx.django.models import CourseKeyField
from openedx_filters import PipelineStep
from openedx_filters.learning.filters import CourseEnrollmentStarted

from .models import Admission

log = logging.getLogger(__name__)


def has_course_role(user, course_key):
    """Course-scoped or institution-wide (org-scoped, empty course_id) access role."""
    from common.djangoapps.student.models import CourseAccessRole  # pylint: disable=import-outside-toplevel

    return CourseAccessRole.objects.filter(
        Q(course_id=course_key) | Q(org=course_key.org, course_id=CourseKeyField.Empty), user=user
    ).exists()


class RequireAdmission(PipelineStep):
    """
    Block enrolment unless EduLage has recorded an active Admission for this learner and
    course run. Platform staff and course team members are exempt so authoring and
    support workflows keep working.
    """

    def run_filter(self, user, course_key, mode):  # pylint: disable=arguments-differ
        if not settings.EDULAGE_ENFORCE_ADMISSION:
            return {}
        if user.is_superuser or user.is_staff or has_course_role(user, course_key):
            return {}
        if Admission.objects.filter(user=user, course_key=course_key, status=Admission.STATUS_ADMITTED).exists():
            return {}
        log.info("edulage: blocked enrolment of %s in %s (no admission)", user.username, course_key)
        raise CourseEnrollmentStarted.PreventEnrollment(
            "Enrolment on EduLage requires an admission decision from the institution. "
            "Apply at https://edulage.org/programmes."
        )
