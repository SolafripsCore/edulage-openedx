import logging

from django.conf import settings
from django.db.models import Q
from opaque_keys.edx.django.models import CourseKeyField
from openedx_filters import PipelineStep
from openedx_filters.learning.filters import CourseEnrollmentStarted, StudentRegistrationRequested

from . import botguard
from .certificates import certificate_context, certificate_template
from .models import Admission, CourseListing, Payment
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
    Enforce the run's enrolment policy (``CourseListing.enrolment_policy``, default admission):

    * ``open_free`` — anyone with an account may enrol;
    * ``open_paid`` — a successful, unconsumed Paystack payment for this learner and run is required;
    * ``admission`` — an active Admission recorded by EduLage is required.

    Platform staff and course team members are exempt so authoring and support workflows keep working.
    """

    def run_filter(self, user, course_key, mode):  # pylint: disable=arguments-differ
        if not settings.EDULAGE_ENFORCE_ADMISSION:
            return {}
        if user.is_superuser or user.is_staff or has_course_role(user, course_key):
            return {}
        if Admission.objects.filter(user=user, course_key=course_key, status=Admission.STATUS_ADMITTED).exists():
            return {}
        listing = CourseListing.objects.filter(course_key=course_key).first()
        policy = listing.enrolment_policy if listing else CourseListing.POLICY_ADMISSION
        if policy == CourseListing.POLICY_OPEN_FREE:
            return {}
        if policy == CourseListing.POLICY_OPEN_PAID:
            if Payment.objects.filter(user=user, course_key=course_key, status=Payment.STATUS_SUCCESS).exists():
                return {}
            log.info("edulage: blocked enrolment of %s in %s (paid run, no payment)", user.username, course_key)
            raise CourseEnrollmentStarted.PreventEnrollment(
                "This course is a paid open-enrolment course. "
                "Complete payment at https://edulage.org/programmes to enrol."
            )
        log.info("edulage: blocked enrolment of %s in %s (no admission)", user.username, course_key)
        raise CourseEnrollmentStarted.PreventEnrollment(
            "This programme requires admission by the institution. "
            f"See {settings.LMS_ROOT_URL}{page_url('pending')} or apply at https://edulage.org/programmes."
        )


class EdulageCertificate(PipelineStep):
    """
    Render web certificates with the EduLage template: the institution awards and issues the
    credential, EduLage records and verifies it. Course-level custom templates configured by
    an institution in Open edX are left untouched.
    """

    def run_filter(self, context, custom_template):  # pylint: disable=arguments-differ
        context.update(certificate_context(context))
        if custom_template:
            return {"context": context, "custom_template": custom_template}
        return {"context": context, "custom_template": certificate_template()}


class GuardRegistration(PipelineStep):
    """
    Bot protection for LMS account creation (``RegistrationView``), which e-mails an activation link to
    the submitted address: refuses registrations that are not part of the EduLage SSO flow (when
    ``EDULAGE_REQUIRE_SSO_REGISTRATION``), random/link-bearing names, and rate-limits the rest.
    """

    def run_filter(self, form_data):  # pylint: disable=arguments-differ
        from crum import get_current_request  # pylint: disable=import-outside-toplevel

        request = get_current_request()
        sso_running = False
        if request is not None and settings.FEATURES.get("ENABLE_THIRD_PARTY_AUTH"):
            from common.djangoapps.third_party_auth import pipeline  # pylint: disable=import-outside-toplevel

            sso_running = pipeline.running(request)
        require_sso = settings.EDULAGE_REQUIRE_SSO_REGISTRATION and settings.FEATURES.get("ENABLE_THIRD_PARTY_AUTH")
        refusal = botguard.registration_refusal(
            form_data.get("name", ""), form_data.get("email", ""),
            botguard.client_ip(request) if request is not None else "", sso_running, bool(require_sso),
        )
        if refusal:
            code, message = refusal
            log.info("edulage: registration refused (%s) for %s", code, form_data.get("email", ""))
            raise StudentRegistrationRequested.PreventRegistration(message, status_code=code)
        return {"form_data": form_data}
