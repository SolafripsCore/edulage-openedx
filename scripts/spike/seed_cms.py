"""Create one course run per pilot institution in Studio.

Run:  tutor local run cms ./manage.py cms shell < scripts/spike/seed_cms.py
"""
from django.contrib.auth import get_user_model
from opaque_keys.edx.keys import CourseKey
from xmodule.modulestore.django import modulestore
from xmodule.modulestore.exceptions import DuplicateCourseError

COURSES = {
    "course-v1:UNIA+CS101+2026": "Introduction to Computing (UNIA)",
    "course-v1:UNIB+MGT101+2026": "Principles of Management (UNIB)",
}
admin = get_user_model().objects.filter(is_superuser=True).order_by("id").first()
store = modulestore()
for key_str, title in COURSES.items():
    key = CourseKey.from_string(key_str)
    try:
        store.create_course(key.org, key.course, key.run, admin.id, fields={"display_name": title})
        print("created", key_str)
    except DuplicateCourseError:
        print("exists", key_str)
