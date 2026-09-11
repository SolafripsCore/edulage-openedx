"""
Admission-gated enrolment proof (Discover -> Apply -> Approve -> Enrol -> Learn).

Discovery/application happen on edulage.org; this script plays the EduLage control plane
calling the Open edX integration API with a client-credentials JWT, and the learner trying to
bypass admissions by enrolling directly.

  SPIKE_TEST_PASSWORD=... EDULAGE_SERVICE_CLIENT_SECRET=... python admission_checks.py
"""
import os
import sys

import requests

from spikelib import LMS, get, sso_session

UNIA = "course-v1:UNIA+CS101+2026"
UNIB = "course-v1:UNIB+MGT101+2026"
API = f"https://{LMS}/edulage/api/v1/admissions/"
results = []


def check(actor, what, ok, observed):
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {actor:16} {what:62} {observed}")


def enrolment(session, course_id):
    r = get(session, f"https://{LMS}/api/enrollment/v1/enrollment/{session.lms_username},{course_id}")
    return bool(r.ok and r.text.strip() and r.json() and r.json().get("is_active"))


def self_enrol(session, course_id):
    csrf = session.get(f"https://{LMS}/csrf/api/v1/token", timeout=60).json()["csrfToken"]
    return session.post(
        f"https://{LMS}/api/enrollment/v1/enrollment",
        json={"course_details": {"course_id": course_id}},
        headers={"X-CSRFToken": csrf, "Referer": f"https://{LMS}/"},
        timeout=60,
    )


# --- EduLage service identity: OAuth2 client credentials -> JWT ----------------------------
tok = requests.post(
    f"https://{LMS}/oauth2/access_token",
    data={
        "grant_type": "client_credentials",
        "client_id": "edulage-control-plane",
        "client_secret": os.environ["EDULAGE_SERVICE_CLIENT_SECRET"],
        "token_type": "jwt",
    },
    timeout=60,
)
check("edulage-svc", "client-credentials JWT issued", tok.ok, tok.status_code)
r = requests.post(
    "https://unia.learn.edulage.org/oauth2/access_token",
    data={
        "grant_type": "client_credentials",
        "client_id": "edulage-control-plane",
        "client_secret": os.environ["EDULAGE_SERVICE_CLIENT_SECRET"],
    },
    timeout=60,
)
check("edulage-svc", "service client refused on a tenant host (eox-tenant)", r.status_code == 401, r.status_code)
svc = requests.Session()
svc.headers["Authorization"] = f"JWT {tok.json()['access_token']}"
svc.headers["User-Agent"] = "edulage-spike/1.0"

r = requests.post(API, json={"username": "ada_legacy", "course_id": UNIA}, timeout=60)
check("anonymous", "admissions API rejects unauthenticated calls", r.status_code in (401, 403), r.status_code)

# --- learner cannot bypass admissions ------------------------------------------------------
ada = sso_session("ada.learner")
u = ada.lms_username
svc.post(API, json={"username": u, "course_id": UNIA, "action": "withdraw", "institution": "UNIA"}, timeout=60)
r = self_enrol(ada, UNIA)
check("ada.learner", "direct enrolment without admission rejected", r.status_code == 403, f"{r.status_code} {r.text[:80]}")
check("ada.learner", "not enrolled after bypass attempt", not enrolment(ada, UNIA), enrolment(ada, UNIA))

# --- institution approves -> EduLage admits -> learner is enrolled --------------------------
body = {"username": u, "course_id": UNIA, "application_id": "APP-2026-0001", "institution": "UNIA", "action": "admit"}
r = svc.post(API, json=body, timeout=60)
check("edulage-svc", "admit creates admission + enrolment", r.ok and r.json()["status"] == "admitted", r.status_code)
check("ada.learner", "enrolled in UNIA CS101 after admission", enrolment(ada, UNIA), True)
r2 = svc.post(API, json=body, timeout=60)
check("edulage-svc", "admit is idempotent on retry", r2.ok and r2.json()["status"] == "admitted" and enrolment(ada, UNIA), r2.status_code)
r = get(ada, f"https://{LMS}/api/courseware/course/{UNIA}")
check("ada.learner", "Start learning: courseware accessible (same SSO session)", r.ok, r.status_code)

# --- negative: wrong institution, unknown user, other course --------------------------------
r = svc.post(API, json={"username": u, "course_id": UNIB, "institution": "UNIA"}, timeout=60)
check("edulage-svc", "UNIA cannot admit into a UNIB course run", r.status_code == 403, r.status_code)
r = svc.post(API, json={"username": "nobody-here", "course_id": UNIA}, timeout=60)
check("edulage-svc", "unknown learner rejected", r.status_code == 404, r.status_code)
r = svc.post(API, json={"username": u, "course_id": "not-a-course"}, timeout=60)
check("edulage-svc", "malformed course run rejected", r.status_code == 400, r.status_code)
r = self_enrol(ada, UNIB)
check("ada.learner", "direct enrolment into UNIB (unadmitted) rejected", r.status_code == 403, r.status_code)

# --- withdrawal / deferment -> enrolment update -------------------------------------------
r = svc.post(API, json={**body, "action": "defer"}, timeout=60)
check("edulage-svc", "defer recorded", r.ok and r.json()["status"] == "deferred", r.status_code)
check("ada.learner", "enrolment deactivated after deferment", not enrolment(ada, UNIA), False)
r = self_enrol(ada, UNIA)
check("ada.learner", "deferred learner cannot re-enrol directly", r.status_code == 403, r.status_code)
r = svc.post(API, json=body, timeout=60)
check("ada.learner", "re-admission restores enrolment", r.ok and enrolment(ada, UNIA), r.status_code)
r = svc.post(API, json={**body, "action": "withdraw"}, timeout=60)
check("edulage-svc", "withdraw recorded", r.ok and r.json()["status"] == "withdrawn", r.status_code)
check("ada.learner", "enrolment deactivated after withdrawal", not enrolment(ada, UNIA), False)

# --- institution staff still enrol without an admission record (course team access) --------
adm = sso_session("unia.admin")
r = self_enrol(adm, UNIA)
check("unia.admin", "course team may enrol in own course (filter bypass for staff)", r.ok, r.status_code)

# --- GET for reconciliation ---------------------------------------------------------------
r = svc.get(API, params={"username": u}, timeout=60)
check("edulage-svc", "GET lists admissions for reconciliation", r.ok and r.json()[0]["status"] == "withdrawn", r.status_code)

print(f"\n{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
