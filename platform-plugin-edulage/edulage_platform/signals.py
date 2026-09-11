"""
Open edX event receivers that trigger EduLage e-mails (LMS only; connected in ``apps.py``).

* ``COURSE_ENROLLMENT_CREATED`` — every enrolment has already passed the admission filter, so a
  new active enrolment is the moment the institution's decision reaches the learner.
* ``CERTIFICATE_CREATED`` — emitted when a certificate is saved in a passing status; the mail is
  sent once the certificate is actually viewable (``downloadable``).
"""
import logging

from django.contrib.auth import get_user_model
from django.dispatch import receiver
from openedx_events.learning.signals import CERTIFICATE_CREATED, COURSE_ENROLLMENT_CREATED

from . import emails

log = logging.getLogger(__name__)
User = get_user_model()

DOWNLOADABLE = "downloadable"


def _user(user_data):
    return User.objects.filter(id=user_data.id).first()


@receiver(COURSE_ENROLLMENT_CREATED, dispatch_uid="edulage_enrolment_email")
def enrolment_created(enrollment, **kwargs):  # pylint: disable=unused-argument
    if not enrollment.is_active:
        return
    user = _user(enrollment.user)
    if user is not None:
        emails.send_enrolment(user, enrollment.course.course_key)


@receiver(CERTIFICATE_CREATED, dispatch_uid="edulage_certificate_email")
def certificate_created(certificate, **kwargs):  # pylint: disable=unused-argument
    if certificate.current_status != DOWNLOADABLE:
        return
    user = _user(certificate.user)
    if user is None:
        return
    from lms.djangoapps.certificates.models import GeneratedCertificate  # pylint: disable=import-outside-toplevel

    cert = GeneratedCertificate.objects.filter(user=user, course_id=certificate.course.course_key).first()
    if cert is None or not cert.verify_uuid:
        return
    emails.send_certificate(user, certificate.course.course_key, cert.verify_uuid)
