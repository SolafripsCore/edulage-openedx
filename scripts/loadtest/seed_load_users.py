"""Create (or remove) throw-away learners for the load test, admitted + enrolled on the UNIA run.

    LOAD_PASSWORD=... LOAD_USERS=20 tutor local run lms ./manage.py lms shell < scripts/loadtest/seed_load_users.py
    LOAD_TEARDOWN=1 tutor local run lms ./manage.py lms shell < scripts/loadtest/seed_load_users.py

Users are `loadtest-NN` with an @example.invalid address so no mail can ever reach anyone; the
welcome/enrolment mails are pre-marked as sent so the run itself never talks to Resend.
"""
import os

from django.contrib.auth import get_user_model
from opaque_keys.edx.keys import CourseKey
from common.djangoapps.student.models import CourseEnrollment, UserProfile
from edulage_platform.models import Admission, SentEmail

COURSE = "course-v1:UNIA+CS101+2026"
N = int(os.environ.get("LOAD_USERS", "20"))
User = get_user_model()

if os.environ.get("LOAD_TEARDOWN"):
    n, _ = User.objects.filter(username__startswith="loadtest-").delete()
    print("deleted", n)
else:
    password = os.environ["LOAD_PASSWORD"]
    key = CourseKey.from_string(COURSE)
    for i in range(1, N + 1):
        username = f"loadtest-{i:02d}"
        user, created = User.objects.get_or_create(
            username=username, defaults={"email": f"{username}@example.invalid", "is_active": True}
        )
        user.set_password(password)
        user.save()
        UserProfile.objects.get_or_create(user=user, defaults={"name": f"Load Tester {i}"})
        SentEmail.objects.get_or_create(user=user, kind=SentEmail.KIND_WELCOME, reference="")
        SentEmail.objects.get_or_create(user=user, kind=SentEmail.KIND_ENROLMENT, reference=COURSE)
        Admission.objects.update_or_create(
            user=user, course_key=key,
            defaults={"application_id": f"load-{i}", "institution": "UNIA",
                      "status": Admission.STATUS_ADMITTED, "mode": "honor"},
        )
        CourseEnrollment.enroll(user, key, mode="honor")
    print("seeded", N)
