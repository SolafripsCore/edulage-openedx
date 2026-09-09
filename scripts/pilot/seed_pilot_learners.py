"""Give the platform admin an admitted, honor-mode enrolment in each pilot run, plus one issued
certificate on the UNIA run so the branded certificate and dashboard action can be demonstrated.

    tutor local run lms ./manage.py lms shell < scripts/pilot/seed_pilot_learners.py
"""
from uuid import uuid4

from django.contrib.auth import get_user_model
from opaque_keys.edx.keys import CourseKey
from common.djangoapps.student.models import CourseEnrollment
from lms.djangoapps.certificates.data import CertificateStatuses
from lms.djangoapps.certificates.models import GeneratedCertificate
from edulage_platform.models import Admission

PILOT_RUNS = {
    "course-v1:UNIA+CS101+2026": "UNIA",
    "course-v1:UNIB+MGT101+2026": "UNIB",
}
CERTIFIED_RUN = "course-v1:UNIA+CS101+2026"

learner = get_user_model().objects.get(username="edulage-admin")

for course_id, org in PILOT_RUNS.items():
    key = CourseKey.from_string(course_id)
    Admission.objects.update_or_create(
        user=learner, course_key=key,
        defaults={"application_id": f"pilot-{org.lower()}-{learner.id}", "institution": org,
                  "status": Admission.STATUS_ADMITTED, "mode": "honor"},
    )
    enrollment = CourseEnrollment.enroll(learner, key, mode="honor")
    if enrollment.mode != "honor" or not enrollment.is_active:
        enrollment.update_enrollment(mode="honor", is_active=True)
    print("enrolled", learner.username, course_id, enrollment.mode)

cert, created = GeneratedCertificate.objects.get_or_create(
    user=learner, course_id=CourseKey.from_string(CERTIFIED_RUN),
    defaults={"status": CertificateStatuses.downloadable, "mode": "honor", "grade": "0.95",
              "name": learner.profile.name or learner.username, "verify_uuid": uuid4().hex,
              "download_url": "", "download_uuid": ""},
)
if cert.status != CertificateStatuses.downloadable or not cert.verify_uuid:
    cert.status = CertificateStatuses.downloadable
    cert.verify_uuid = cert.verify_uuid or uuid4().hex
    cert.save()
print("certificate", cert.verify_uuid, "created" if created else "existing")
