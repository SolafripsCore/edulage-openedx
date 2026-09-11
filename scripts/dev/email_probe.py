"""
Exercise the enrolment e-mail trigger on the pilot with a throw-away learner.
Run inside the LMS container:  ./manage.py lms shell < scripts/dev/email_probe.py
"""
from uuid import uuid4

from django.contrib.auth import get_user_model
from common.djangoapps.student.models import CourseEnrollment, UserProfile
from lms.djangoapps.certificates.data import CertificateStatuses
from lms.djangoapps.certificates.models import GeneratedCertificate
from opaque_keys.edx.keys import CourseKey
from edulage_platform.models import Admission, SentEmail

User = get_user_model()
user, _ = User.objects.get_or_create(
    username="email-probe", defaults={"email": "email-probe@example.test", "is_active": True}
)
UserProfile.objects.get_or_create(user=user, defaults={"name": "Probe Learner"})
key = CourseKey.from_string("course-v1:UNIB+MGT101+2026")
Admission.objects.get_or_create(
    user=user, course_key=key, defaults={"application_id": "probe", "institution": "UNIB", "edulage_sub": "probe"}
)
SentEmail.objects.filter(user=user).delete()
if CourseEnrollment.is_enrolled(user, key):
    CourseEnrollment.unenroll(user, key)
CourseEnrollment.enroll(user, key, check_access=False)
# re-activating the same enrolment must not send a second notice
CourseEnrollment.unenroll(user, key)
CourseEnrollment.enroll(user, key, check_access=False)
cert, _ = GeneratedCertificate.objects.get_or_create(
    user=user, course_id=key, defaults={"mode": "honor", "grade": "0.9", "name": "Probe Learner"}
)
cert.status = CertificateStatuses.downloadable
cert.verify_uuid = cert.verify_uuid or uuid4().hex  # generation.py sets this in the same save
cert.save()
cert.save()  # a second save (grade recalculation) must not send a second notice
print("sent rows:", list(SentEmail.objects.filter(user=user).values_list("kind", "reference")))
