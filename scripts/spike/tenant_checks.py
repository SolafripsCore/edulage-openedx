"""Positive and negative tenant-isolation checks across LMS, Studio and tenant hosts.

Usage: SPIKE_TEST_PASSWORD=... EDULAGE_SERVICE_CLIENT_SECRET=... python scripts/spike/tenant_checks.py

Per-course-run roles (instructor, TA) are not token claims: the EduLage control plane pushes them
through the roles API, so this suite grants them first, exactly as EduLage would.

Each line prints PASS/FAIL, the actor, the check and the observed HTTP status. Exit code is
non-zero if any check fails, so this can be re-run after every configuration change.
"""
import os
import sys

import requests

from spikelib import CMS, LMS, get, sso_session, studio_login

ROLES_API = f"https://{LMS}/edulage/api/v1/roles/"

UNIA = "course-v1:UNIA+CS101+2026"
UNIB = "course-v1:UNIB+MGT101+2026"
UNIA_HOST = "unia.learn.edulage.org"
UNIB_HOST = "unib.learn.edulage.org"

results = []


def check(actor, what, ok, observed):
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {actor:16} {what:60} {observed}")


def course_ids(resp):
    if resp.status_code != 200:
        return f"HTTP {resp.status_code}"
    return sorted(c["id"] if isinstance(c, dict) else c for c in resp.json().get("results", []))


def grant_run_roles(username, roles):
    tok = requests.post(
        f"https://{LMS}/oauth2/access_token",
        data={"grant_type": "client_credentials", "client_id": "edulage-control-plane",
              "client_secret": os.environ["EDULAGE_SERVICE_CLIENT_SECRET"], "token_type": "jwt"},
        timeout=60,
    )
    r = requests.put(ROLES_API, json={"username": username, "roles": roles},
                     headers={"Authorization": f"JWT {tok.json()['access_token']}"}, timeout=60)
    check("edulage-svc", f"roles API grants {roles} to {username}", r.status_code == 200, r.status_code)


# --- anonymous: tenant hosts only expose their own institution's courses -------------------
anon = requests.Session()
for host, expect in ((UNIA_HOST, [UNIA]), (UNIB_HOST, [UNIB])):
    got = course_ids(anon.get(f"https://{host}/api/courses/v1/courses/", timeout=60))
    check("anonymous", f"{host} course list is institution-scoped", got == expect, got)
got = course_ids(anon.get(f"https://{LMS}/api/courses/v1/courses/", timeout=60))
check("anonymous", f"{LMS} (platform host) hides tenant-claimed orgs", UNIA not in got and UNIB not in got, got)

# --- UNIA institution admin ---------------------------------------------------------------
a = sso_session("unia.admin")
studio_login(a)
home = get(a, f"https://{CMS}/api/contentstore/v1/home/courses")
mine = sorted(c["course_key"] for c in home.json().get("courses", [])) if home.ok else f"HTTP {home.status_code}"
check("unia.admin", "Studio home lists only UNIA courses", mine == [UNIA], mine)
r = get(a, f"https://{CMS}/api/contentstore/v1/course_settings/{UNIA}")
check("unia.admin", "Studio course settings of own course", r.status_code == 200, r.status_code)
r = get(a, f"https://{CMS}/api/contentstore/v1/course_settings/{UNIB}")
check("unia.admin", "Studio course settings of UNIB course denied", r.status_code == 403, r.status_code)
r = get(a, f"https://{CMS}/api/contentstore/v1/course_team/{UNIB}")
check("unia.admin", "Studio course team API for UNIB denied", r.status_code in (403, 404), r.status_code)
r = get(a, f"https://{LMS}/api/instructor/v1/tasks/{UNIA}")
check("unia.admin", "LMS instructor API, own course", r.status_code == 200, r.status_code)
r = get(a, f"https://{LMS}/api/instructor/v1/tasks/{UNIB}")
check("unia.admin", "LMS instructor API for UNIB denied", r.status_code in (403, 404), r.status_code)
r = get(a, f"https://{LMS}/courses/{UNIB}/instructor/api/get_students_features/csv")
check("unia.admin", "UNIB learner export denied", r.status_code in (403, 404), r.status_code)
r = get(a, f"https://{LMS}/api/enrollment/v1/enrollments?course_id={UNIB}")
check("unia.admin", "UNIB enrolment list via enrollment API denied", r.status_code in (403, 404, 401) or r.json().get("results") == [], r.status_code)

# --- UNIB instructor (course-scoped) ------------------------------------------------------
b = sso_session("unib.instructor")
grant_run_roles(b.lms_username, [f"instructor:{UNIB}"])
studio_login(b)
home = get(b, f"https://{CMS}/api/contentstore/v1/home/courses")
mine = sorted(c["course_key"] for c in home.json().get("courses", [])) if home.ok else f"HTTP {home.status_code}"
check("unib.instructor", "Studio home lists only UNIB MGT101", mine == [UNIB], mine)
r = get(b, f"https://{CMS}/api/contentstore/v1/course_settings/{UNIA}")
check("unib.instructor", "Studio course settings of UNIA course denied", r.status_code == 403, r.status_code)
r = get(b, f"https://{LMS}/api/instructor/v1/tasks/{UNIA}")
check("unib.instructor", "LMS instructor API, UNIA denied", r.status_code in (403, 404), r.status_code)

# --- UNIB teaching assistant: limited staff, no Studio ------------------------------------
t = sso_session("unib.ta")
grant_run_roles(t.lms_username, [f"teaching_assistant:{UNIB}"])
studio_login(t)
home = get(t, f"https://{CMS}/api/contentstore/v1/home/courses")
mine = sorted(c["course_key"] for c in home.json().get("courses", [])) if home.ok else f"HTTP {home.status_code}"
check("unib.ta", "Studio: TA has no authoring access", mine == [] or home.status_code == 403, mine)
r = get(t, f"https://{LMS}/api/instructor/v1/tasks/{UNIB}")
check("unib.ta", "LMS instructor API (limited) on own course", r.status_code == 200, r.status_code)

# --- learner: no staff surfaces anywhere --------------------------------------------------
l = sso_session("ada.learner")
r = get(l, f"https://{LMS}/api/instructor/v1/tasks/{UNIA}")
check("ada.learner", "learner cannot open instructor API", r.status_code in (403, 404), r.status_code)
studio_login(l)
home = get(l, f"https://{CMS}/api/contentstore/v1/home/courses")
mine = sorted(c["course_key"] for c in home.json().get("courses", [])) if home.ok else f"HTTP {home.status_code}"
check("ada.learner", "learner sees no Studio courses", mine == [] or home.status_code in (302, 403), mine)

# --- OEC support: scoped learner summary only, no Open edX support console or course authority
o = sso_session("oec.support")
r = get(o, f"https://{LMS}/support/")
check("oec.support", "Open edX support console denied (scoped SupportScope instead)", r.status_code in (302, 403), r.status_code)
r = get(o, f"https://{LMS}/edulage/api/v1/support/learners/?username=ada_legacy")
check("oec.support", "scoped learner summary (UNIA) accessible", r.status_code == 200, r.status_code)
r = get(o, f"https://{LMS}/api/instructor/v1/tasks/{UNIB}")
check("oec.support", "no instructor API", r.status_code in (403, 404), r.status_code)

# --- EduLage central admin: platform-wide oversight ---------------------------------------
e = sso_session("edu.admin")
studio_login(e)
home = get(e, f"https://{CMS}/api/contentstore/v1/home/courses")
mine = sorted(c["course_key"] for c in home.json().get("courses", [])) if home.ok else f"HTTP {home.status_code}"
check("edu.admin", "Studio home lists courses of every institution", UNIA in mine and UNIB in mine, mine)
for ck in (UNIA, UNIB):
    r = get(e, f"https://{LMS}/api/instructor/v1/tasks/{ck}")
    check("edu.admin", f"instructor API {ck.split(':')[1]}", r.status_code == 200, r.status_code)
r = get(e, f"https://{LMS}/support/")
check("edu.admin", "support dashboard accessible", r.status_code == 200, r.status_code)

print(f"\n{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
