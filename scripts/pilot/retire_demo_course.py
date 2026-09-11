"""Remove the stock Open edX demonstration course from the pilot platform.

    tutor local run cms ./manage.py cms shell < scripts/pilot/retire_demo_course.py

Enrolments, certificates and grades for the demo course go with it (it was never institution content).
"""
from django.contrib.auth import get_user_model
from opaque_keys.edx.keys import CourseKey
from cms.djangoapps.contentstore.utils import delete_course
from xmodule.modulestore.django import modulestore
from common.djangoapps.student.models import CourseEnrollment
from lms.djangoapps.certificates.models import GeneratedCertificate
from openedx.core.djangoapps.content.course_overviews.models import CourseOverview
from edulage_platform.models import Admission, CourseListing

DEMO = CourseKey.from_string("course-v1:OpenedX+DemoX+DemoCourse")
admin = get_user_model().objects.filter(is_superuser=True).order_by("id").first()

if modulestore().has_course(DEMO):
    delete_course(DEMO, admin.id, keep_instructors=False)
    print("deleted", DEMO)
else:
    print("not present", DEMO)

print("enrolments removed", CourseEnrollment.objects.filter(course_id=DEMO).delete()[0])
print("certificates removed", GeneratedCertificate.objects.filter(course_id=DEMO).delete()[0])
print("admissions removed", Admission.objects.filter(course_key=DEMO).delete()[0])
print("listings removed", CourseListing.objects.filter(course_key=DEMO).delete()[0])
print("overview removed", CourseOverview.objects.filter(id=DEMO).delete()[0])
