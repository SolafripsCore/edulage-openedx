"""
Open edX event receivers (LMS only; connected in ``apps.py``): learner e-mails and the
control-plane outbox (``events.emit``).

* ``COURSE_ENROLLMENT_CREATED`` — every enrolment has already passed the admission filter, so a
  new active enrolment is the moment the institution's decision reaches the learner.
* ``COURSE_ENROLLMENT_CHANGED`` — deactivation (unenrol / withdrawal) → ``enrolment.deactivated``.
* ``PERSISTENT_GRADE_SUMMARY_CHANGED`` — a passing course grade → ``course.completed``.
* ``CERTIFICATE_CREATED`` / ``CERTIFICATE_REVOKED`` — the mail is sent once the certificate is
  actually viewable (``downloadable``); both are forwarded as events.
"""
import logging

from django.contrib.auth import get_user_model
from django.dispatch import receiver
from openedx_events.learning.signals import (
    CERTIFICATE_CREATED, CERTIFICATE_REVOKED, COURSE_ENROLLMENT_CHANGED, COURSE_ENROLLMENT_CREATED,
    PERSISTENT_GRADE_SUMMARY_CHANGED,
)

from . import emails, events, identity

log = logging.getLogger(__name__)
User = get_user_model()

DOWNLOADABLE = "downloadable"


def _user(user_data):
    return User.objects.filter(id=user_data.id).first()


@receiver(COURSE_ENROLLMENT_CREATED, dispatch_uid="campus_enrolment_email")
def enrolment_created(enrollment, **kwargs):  # pylint: disable=unused-argument
    if not enrollment.is_active:
        return
    user = _user(enrollment.user)
    if user is not None:
        emails.send_enrolment(user, enrollment.course.course_key)
        events.emit(
            "enrolment.created",
            {"username": user.username, "mode": enrollment.mode},
            course_key=enrollment.course.course_key, sub=identity.sub_for_user(user) or "",
        )


@receiver(COURSE_ENROLLMENT_CHANGED, dispatch_uid="campus_enrolment_changed_event")
def enrolment_changed(enrollment, **kwargs):  # pylint: disable=unused-argument
    if enrollment.is_active:
        return
    user = _user(enrollment.user)
    if user is not None:
        events.emit(
            "enrolment.deactivated",
            {"username": user.username, "mode": enrollment.mode},
            course_key=enrollment.course.course_key, sub=identity.sub_for_user(user) or "",
        )


@receiver(PERSISTENT_GRADE_SUMMARY_CHANGED, dispatch_uid="campus_grade_event")
def grade_changed(grade, **kwargs):  # pylint: disable=unused-argument
    if not grade.passed_timestamp:
        return
    user = _user(grade.user)
    if user is not None:
        events.emit(
            "course.completed",
            {"username": user.username, "percent_grade": grade.percent_grade, "letter_grade": grade.letter_grade,
             "passed_at": grade.passed_timestamp.isoformat()},
            course_key=grade.course.course_key, sub=identity.sub_for_user(user) or "",
            occurred=grade.passed_timestamp,
        )


@receiver(CERTIFICATE_REVOKED, dispatch_uid="campus_certificate_revoked_event")
def certificate_revoked(certificate, **kwargs):  # pylint: disable=unused-argument
    user = _user(certificate.user)
    if user is not None:
        events.emit(
            "certificate.revoked",
            {"username": user.username, "mode": certificate.mode},
            course_key=certificate.course.course_key, sub=identity.sub_for_user(user) or "",
        )


@receiver(CERTIFICATE_CREATED, dispatch_uid="campus_certificate_email")
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
    events.emit(
        "certificate.issued",
        {"username": user.username, "mode": certificate.mode, "verify_uuid": cert.verify_uuid,
         "grade": certificate.grade},
        course_key=certificate.course.course_key, sub=identity.sub_for_user(user) or "",
    )
