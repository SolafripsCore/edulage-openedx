"""
Proofs for the EduLage course-listing metadata behind the "My learning" cards (theme item 2):

  * integration layer upserts institution / classification / programme per course run (idempotent PUT)
  * invalid course ids and unknown classifications are rejected, nothing partially written
  * a learner only ever receives metadata for their own active enrolments
  * runs without a listing fall back to the Open edX organisation, labelled "Course"
  * anonymous and non-integration callers are refused

Runs inside the LMS shell (no secrets needed — views are exercised through DRF's request factory
with force_authenticate, so the auth/permission classes are still evaluated):

  tutor local run lms ./manage.py lms shell < scripts/spike/listing_checks.py
"""
import json

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from rest_framework.test import APIRequestFactory, force_authenticate
from opaque_keys.edx.keys import CourseKey

from common.djangoapps.student.models import CourseEnrollment, UserProfile
from edulage_platform.api.views import DashboardCoursesView, ListingsView
from edulage_platform.models import Admission, CourseListing

User = get_user_model()
UNIA = "course-v1:UNIA+CS101+2026"
UNIB = "course-v1:UNIB+MGT101+2026"
LISTINGS = "/edulage/api/v1/listings/"
DASHBOARD = "/edulage/api/v1/dashboard/courses/"
results = []


def check(actor, what, ok, observed):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {actor:14} {what:62} {str(observed)[:70]}")


factory = APIRequestFactory()


def call(view, request, user):
    if user is not None:
        force_authenticate(request, user=user)
    response = view.as_view()(request)
    response.render()
    response.json = lambda: json.loads(response.content)
    return response


def put(user, payload):
    return call(ListingsView, factory.put(LISTINGS, payload, format="json"), user)


def dashboard(user):
    return call(DashboardCoursesView, factory.get(DASHBOARD), user)


integration_group, _ = Group.objects.get_or_create(name=settings.EDULAGE_INTEGRATION_GROUP)
integration = User.objects.filter(groups=integration_group).first()
learner, _ = User.objects.get_or_create(username="listing_probe", defaults={"email": "listing_probe@example.invalid"})
stranger, _ = User.objects.get_or_create(username="listing_stranger", defaults={"email": "listing_stranger@example.invalid"})
for probe in (learner, stranger):
    UserProfile.objects.get_or_create(user=probe, defaults={"name": probe.username})


def admit_and_enrol(user, course_id, institution):
    """Enrolment follows admission on EduLage (RequireAdmission filter) — even from the shell."""
    key = CourseKey.from_string(course_id)
    Admission.objects.update_or_create(
        user=user, course_key=key,
        defaults={"application_id": f"probe-{user.username}", "institution": institution, "status": Admission.STATUS_ADMITTED},
    )
    CourseEnrollment.enroll(user, key, check_access=False)


admit_and_enrol(learner, UNIA, "UNIA")
admit_and_enrol(stranger, UNIB, "UNIB")
CourseListing.objects.filter(course_key__in=[UNIA, UNIB]).delete()

# --- integration API -------------------------------------------------------
r = put(None, {"listings": []})
check("anonymous", "PUT listings refused", r.status_code in (401, 403), r.status_code)
r = put(learner, {"listings": []})
check("learner", "PUT listings refused (not integration)", r.status_code == 403, r.status_code)

payload = {"listings": [{
    "course_id": UNIA, "institution": "UNIA", "institution_name": "University A",
    "institution_url": "https://edulage.org/institutions/unia", "classification": "degree", "credential": "BSc",
    "programme_title": "BSc Computer Science", "programme_url": "https://edulage.org/programmes/unia-bsc-cs",
    "delivery_mode": "Fully online",
}]}
r = put(integration, payload)
body = r.json() if r.status_code == 200 else {}
check("integration", "PUT listings upserts UNIA run", r.status_code == 200 and body["listings"][0]["classification_label"] == "Degree programme", r.status_code)
r2 = put(integration, payload)
check("integration", "PUT is idempotent (one row)", r2.status_code == 200 and CourseListing.objects.filter(course_key=UNIA).count() == 1, CourseListing.objects.filter(course_key=UNIA).count())

before = CourseListing.objects.count()
r = put(integration, {"listings": [{"course_id": UNIB, "institution_name": "University B"}, {"course_id": "not-a-course"}]})
check("integration", "invalid course_id -> 400, nothing written", r.status_code == 400 and CourseListing.objects.count() == before, r.status_code)
r = put(integration, {"listings": [{"course_id": UNIB, "classification": "bootcamp"}]})
check("integration", "unknown classification -> 400", r.status_code == 400 and not CourseListing.objects.filter(course_key=UNIB).exists(), r.status_code)
r = put(integration, {"listings": {"course_id": UNIB}})
check("integration", "non-list payload -> 400", r.status_code == 400, r.status_code)

# --- learner dashboard API -------------------------------------------------
r = dashboard(None)
check("anonymous", "GET dashboard/courses refused", r.status_code in (401, 403), r.status_code)

r = dashboard(learner)
rows = {c["course_id"]: c for c in r.json()["courses"]} if r.status_code == 200 else {}
check("learner", "sees own enrolment only", r.status_code == 200 and set(rows) == {UNIA}, sorted(rows))
unia = rows.get(UNIA, {})
check("learner", "card metadata from EduLage listing", unia.get("institution_name") == "University A" and unia.get("credential") == "BSc"
      and unia.get("programme_url", "").startswith("https://edulage.org/"), unia.get("institution_name"))

r = dashboard(stranger)
rows = {c["course_id"]: c for c in r.json()["courses"]} if r.status_code == 200 else {}
check("stranger", "does not see the other learner's run", set(rows) == {UNIB}, sorted(rows))
unib = rows.get(UNIB, {})
check("stranger", "no listing -> Open edX org fallback, label 'Course'", unib.get("institution") == "UNIB" and unib.get("classification_label") == "Course" and unib.get("classification") == "", unib.get("classification_label"))

CourseEnrollment.unenroll(learner, CourseKey.from_string(UNIA))
r = dashboard(learner)
check("learner", "inactive enrolment disappears", r.status_code == 200 and r.json()["courses"] == [], len(r.json().get("courses", [])))

# --- cleanup (users cascade to admissions and enrolments) -------------------
CourseListing.objects.filter(course_key__in=[UNIA, UNIB]).delete()
CourseEnrollment.unenroll(stranger, CourseKey.from_string(UNIB))
User.objects.filter(username__in=["listing_probe", "listing_stranger"]).delete()

print(f"\n{sum(results)}/{len(results)} passed")
