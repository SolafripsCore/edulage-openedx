import logging

from django.conf import settings
from django.db.models import Q
from opaque_keys.edx.django.models import CourseKeyField
from openedx_filters import PipelineStep
from openedx_filters.learning.filters import CourseEnrollmentStarted

from .certificates import certificate_context, certificate_template
from . import hooks
from .models import Admission
from .status import page_url

log = logging.getLogger(__name__)


def has_course_role(user, course_key):
    """Course-scoped or institution-wide (org-scoped, empty course_id) access role."""
    from common.djangoapps.student.models import CourseAccessRole  # pylint: disable=import-outside-toplevel

    return CourseAccessRole.objects.filter(
        Q(course_id=course_key) | Q(org=course_key.org, course_id=CourseKeyField.Empty), user=user
    ).exists()


class RequireAdmission(PipelineStep):
    """
    Enforce the run's enrolment policy (``hooks.enrolment_policy``, default admission):

    * ``open`` — the product layer allows self-enrolment (free, or paid and settled);
    * ``admission`` — an active Admission recorded by the control plane is required.

    Platform staff and course team members are exempt so authoring and support workflows keep working.
    """

    def run_filter(self, user, course_key, mode):  # pylint: disable=arguments-differ
        if not settings.CAMPUS_ENFORCE_ADMISSION:
            return {}
        if user.is_superuser or user.is_staff or has_course_role(user, course_key):
            return {}
        if Admission.objects.filter(user=user, course_key=course_key, status=Admission.STATUS_ADMITTED).exists():
            return {}
        policy = hooks.enrolment_policy(user, course_key)
        if policy == hooks.POLICY_OPEN:
            return {}
        if policy.startswith("blocked:"):
            log.info("campus: blocked enrolment of %s in %s (%s)", user.username, course_key, policy)
            raise CourseEnrollmentStarted.PreventEnrollment(policy.split(":", 1)[1])
        log.info("campus: blocked enrolment of %s in %s (no admission)", user.username, course_key)
        raise CourseEnrollmentStarted.PreventEnrollment(
            "This programme requires admission by the institution. "
            f"See {settings.LMS_ROOT_URL}{page_url('pending')}."
        )


class CampusCertificate(PipelineStep):
    """
    Render web certificates with the campus template: the institution awards and issues the
    credential, the platform records and verifies it. Course-level custom templates configured by
    an institution in Open edX are left untouched.
    """

    def run_filter(self, context, custom_template):  # pylint: disable=arguments-differ
        context.update(certificate_context(context))
        if custom_template:
            return {"context": context, "custom_template": custom_template}
        return {"context": context, "custom_template": certificate_template()}
