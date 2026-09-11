"""
Production-hardening proofs on top of the spike (team review items 2-6, 10):

  * admission before first LMS login, keyed to the immutable EduLage `sub` (202 pending -> applied at SSO)
  * collision-safe account linking: verified email only, refused when the LMS account is bound elsewhere
  * per-course-run entitlements via the audited roles API, reconciled separately from token claims
  * OEC support scoped to institution / run (no SupportStaffRole)
  * immediate suspension: existing session, tokens and roles revoked without waiting for next login
  * shorter sessions for staff; integration API restricted to the integration group

Runs from a workstation; a few fixtures need the LMS shell and the IdP admin, reached over SSH:

  SPIKE_SSH="ssh -i ~/.ssh/key <admin-user>@host" SPIKE_TEST_PASSWORD=... EDULAGE_SERVICE_CLIENT_SECRET=... \
      python hardening_checks.py

<admin-user> is a named administrator created by scripts/harden.sh (sudo + docker group); root SSH is disabled.
"""
import os
import shlex
import subprocess
import sys
import time

import requests

from spikelib import LMS, get, sso_session

UNIA = "course-v1:UNIA+CS101+2026"
UNIB = "course-v1:UNIB+MGT101+2026"
API = f"https://{LMS}/edulage/api/v1"
SSH = shlex.split(os.environ["SPIKE_SSH"])
results = []


def check(actor, what, ok, observed):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {actor:16} {what:66} {str(observed)[:70]}")


def ssh(cmd, stdin=""):
    return subprocess.run(SSH + [cmd], input=stdin, capture_output=True, text=True, timeout=300).stdout


def lms_shell(code):
    """Run Python in the LMS; the last line printed is returned."""
    out = ssh("docker exec -i tutor_local-lms-1 python manage.py lms shell 2>/dev/null", code)
    lines = [l for l in out.strip().splitlines() if l and not l.startswith(" ")]
    return lines[-1] if lines else ""


def idp_sub(username):
    return ssh(
        "docker exec edulage-keycloak /opt/keycloak/bin/kcadm.sh get users -r edulage "
        f"-q username={username} -q exact=true --fields id --format csv --noquotes"
    ).strip()


def audit(username_or_sub, event):
    out = lms_shell(
        "from edulage_platform.models import IdentityAudit\n"
        "from django.db.models import Q\n"
        f"print(IdentityAudit.objects.filter(Q(user__username={username_or_sub!r})|Q(edulage_sub={username_or_sub!r})|Q(email={username_or_sub!r}), event={event!r}).count())"
    )
    return int(out) if out.isdigit() else 0


def enrolment(session, course_id):
    r = get(session, f"https://{LMS}/api/enrollment/v1/enrollment/{session.lms_username},{course_id}")
    return bool(r.ok and r.text.strip() and r.json() and r.json().get("is_active"))


def service_session():
    tok = requests.post(
        f"https://{LMS}/oauth2/access_token",
        data={"grant_type": "client_credentials", "client_id": "edulage-control-plane",
              "client_secret": os.environ["EDULAGE_SERVICE_CLIENT_SECRET"], "token_type": "jwt"},
        timeout=60,
    )
    s = requests.Session()
    s.headers["Authorization"] = f"JWT {tok.json()['access_token']}"
    s.headers["User-Agent"] = "edulage-spike/1.0"
    return s


svc = service_session()
ssh("docker exec edulage-keycloak /opt/keycloak/bin/kcadm.sh config credentials --server http://localhost:8080 "
    "--realm master --user admin --password \"$(sudo -n grep KEYCLOAK_ADMIN_PASSWORD /home/tutor/infra/keycloak/.env | cut -d= -f2)\"")

# --- 1. integration API is restricted to the integration group -------------------------------
lms_shell("from django.contrib.auth.models import User; u=User.objects.get(username='edulage-integration'); u.groups.clear(); print('ok')")
r = svc.get(f"{API}/admissions/", timeout=60)
check("edulage-svc", "staff service user outside integration group is refused", r.status_code == 403, r.status_code)
lms_shell("from django.contrib.auth.models import User, Group; u=User.objects.get(username='edulage-integration'); "
          "u.groups.add(Group.objects.get(name='edulage_integration')); print('ok')")
r = svc.get(f"{API}/admissions/", timeout=60)
check("edulage-svc", "same user inside integration group is accepted", r.status_code == 200, r.status_code)

# --- 2. admission before first login, keyed to sub -------------------------------------------
bola_sub = idp_sub("bola.pending")
lms_shell("from django.contrib.auth.models import User; from edulage_platform.models import Admission; "
          f"User.objects.filter(email='bola.pending@example.org').delete(); Admission.objects.filter(edulage_sub={bola_sub!r}).delete(); print('ok')")
r = svc.post(f"{API}/admissions/", json={"sub": bola_sub, "course_id": UNIA, "institution": "UNIA", "application_id": "APP-BOLA-1"}, timeout=60)
check("edulage-svc", "admit applicant with no LMS account -> 202 pending", r.status_code == 202 and r.json()["pending"], r.status_code)
r = svc.post(f"{API}/admissions/", json={"sub": bola_sub, "course_id": UNIA, "institution": "UNIA", "application_id": "APP-BOLA-1"}, timeout=60)
check("edulage-svc", "pending admit is idempotent", r.status_code == 202, r.status_code)
r = svc.get(f"{API}/admissions/", params={"sub": bola_sub}, timeout=60)
check("edulage-svc", "pending admission visible by sub (username null)", r.ok and r.json()[0]["username"] is None, r.json()[0]["username"] if r.ok else r.status_code)
bola = sso_session("bola.pending")
check("bola.pending", "first SSO login creates LMS account", bool(bola.lms_username), bola.lms_username)
check("bola.pending", "pending admission applied: enrolled in UNIA CS101 at first login", enrolment(bola, UNIA), enrolment(bola, UNIA))
r = svc.get(f"{API}/admissions/", params={"sub": bola_sub}, timeout=60)
check("edulage-svc", "admission now attached to the LMS user, not pending", r.ok and r.json()[0]["username"] == bola.lms_username and not r.json()[0]["pending"], r.json()[0] if r.ok else r.status_code)
check("audit", "admission_applied + created audit rows written", audit(bola_sub, "admission_applied") >= 1 and audit(bola_sub, "created") >= 1, (audit(bola_sub, "admission_applied"), audit(bola_sub, "created")))
r = get(bola, f"https://{LMS}/courses/{UNIA}/courseware")
check("bola.pending", "Start learning works in the same session (no second login)", r.status_code in (200, 302) and "login" not in r.headers.get("Location", ""), (r.status_code, r.headers.get("Location", "")[:60]))

# --- 3. collision-safe linking ---------------------------------------------------------------
check("audit", "ada.learner <-> ada_legacy link was audited (verified email, single match)", audit("ada_legacy", "linked") >= 1, audit("ada_legacy", "linked"))

lms_shell("from django.contrib.auth import get_user_model; from common.djangoapps.student.models import UserProfile; U=get_user_model(); "
          "u,_=U.objects.get_or_create(username='uv_legacy', defaults={'email':'uv.learner@example.org','is_active':True}); "
          "u.set_password('x'*30); u.save(); UserProfile.objects.get_or_create(user=u, defaults={'name':'UV'}); "
          "from social_django.models import UserSocialAuth; UserSocialAuth.objects.filter(user=u).delete(); print('ok')")
try:
    uv = sso_session("uv.learner")
    linked = uv.lms_username == "uv_legacy"
except RuntimeError:
    linked = False
check("uv.learner", "unverified email is NOT linked to the existing account", not linked, "not linked" if not linked else "LINKED")
check("audit", "link_refused audited for unverified email", audit("uv.learner@example.org", "link_refused") >= 1, audit("uv.learner@example.org", "link_refused"))

try:
    dupe = sso_session("dupe.learner")
    linked = dupe.lms_username == "dupe_taken"
except RuntimeError:
    linked = False
check("dupe.learner", "account already bound to another EduLage sub is NOT linked", not linked, "not linked" if not linked else "LINKED")
check("audit", "link_refused audited (bound to another identity)", audit("dupe.learner@example.org", "link_refused") >= 1, audit("dupe.learner@example.org", "link_refused"))

# --- 4. roles API: compact token claims + per-run entitlements from EduLage -------------------
instr = sso_session("unib.instructor")          # token claim is only `learner` now
instr_sub = idp_sub("unib.instructor")
INSTR = f"https://{LMS}/api/instructor/v1/tasks"
r = get(instr, f"{INSTR}/{UNIB}")
check("unib.instructor", "no instructor access from token claims alone", r.status_code != 200, r.status_code)
r = svc.put(f"{API}/roles/", json={"sub": instr_sub, "roles": ["edulage_admin"]}, timeout=60)
check("edulage-svc", "roles API refuses edulage_admin", r.status_code == 400, r.status_code)
r = svc.put(f"{API}/roles/", json={"sub": instr_sub, "roles": [f"instructor:{UNIB}"]}, timeout=60)
check("edulage-svc", "roles API grants instructor on UNIB MGT101 (source=api)", r.ok and any(x["source"] == "api" and x["role"] == "instructor" for x in r.json()["roles"]), r.json()["roles"] if r.ok else r.status_code)
r = get(instr, f"{INSTR}/{UNIB}")
check("unib.instructor", "instructor API reachable in the existing session", r.status_code == 200, r.status_code)
r = get(instr, f"{INSTR}/{UNIA}")
check("unib.instructor", "still no access to UNIA's course run", r.status_code != 200, r.status_code)
r = svc.put(f"{API}/roles/", json={"sub": instr_sub, "roles": []}, timeout=60)
r2 = get(instr, f"{INSTR}/{UNIB}")
check("edulage-svc", "roles API revocation takes effect immediately", r.ok and r2.status_code != 200, r2.status_code)
check("audit", "roles_synced audited", audit(instr_sub, "roles_synced") >= 1, audit(instr_sub, "roles_synced"))
admin_sub = idp_sub("unia.admin")
unia_admin = sso_session("unia.admin")
r = svc.put(f"{API}/roles/", json={"sub": admin_sub, "roles": []}, timeout=60)
r2 = get(unia_admin, f"{INSTR}/{UNIA}")
check("unia.admin", "API reconciliation does not touch token-sourced institution_admin", r.ok and r2.status_code == 200, r2.status_code)

# --- 5. OEC support scoped by institution --------------------------------------------------
ada = sso_session("ada.learner")
svc.post(f"{API}/admissions/", json={"username": ada.lms_username, "course_id": UNIA, "institution": "UNIA"}, timeout=60)
oec = sso_session("oec.support")
r = get(oec, f"https://{LMS}/support/")
check("oec.support", "no Open edX SupportStaffRole (support console denied)", r.status_code in (302, 403), r.status_code)
r = oec.get(f"{API}/support/learners/", params={"username": ada.lms_username}, timeout=60)
check("oec.support", "in-scope (UNIA) learner summary returned", r.status_code == 200 and r.json()["enrolments"], r.status_code)
check("oec.support", "summary contains no grades / PII beyond username", r.ok and set(r.json()) == {"username", "enrolments", "admissions"}, sorted(r.json()) if r.ok else r.status_code)
r = oec.get(f"{API}/support/learners/", params={"username": instr.lms_username}, timeout=60)
check("oec.support", "UNIB-only learner is not visible to a UNIA-scoped officer", r.status_code == 404, r.status_code)
r = oec.get(f"{API}/admissions/", timeout=60)
check("oec.support", "OEC officer cannot call the integration API", r.status_code == 403, r.status_code)
r = ada.get(f"{API}/support/learners/", params={"username": bola.lms_username}, timeout=60)
check("ada.learner", "learner without support scope is refused", r.status_code == 403, r.status_code)
check("audit", "support_lookup audited", audit(ada.lms_username, "support_lookup") >= 1, audit(ada.lms_username, "support_lookup"))

# --- 6. immediate suspension -----------------------------------------------------------------
ta = sso_session("unib.ta")
ta_sub = idp_sub("unib.ta")
svc.put(f"{API}/roles/", json={"sub": ta_sub, "roles": [f"teaching_assistant:{UNIB}"]}, timeout=60)
r = get(ta, f"https://{LMS}/api/user/v1/me")
check("unib.ta", "precondition: signed in, /me 200", r.status_code == 200, r.status_code)
r = svc.post(f"{API}/users/status/", json={"sub": ta_sub, "status": "suspended", "reason": "review"}, timeout=60)
check("edulage-svc", "suspend -> 200", r.ok and r.json()["status"] == "suspended", r.status_code)
r = get(ta, f"https://{LMS}/api/user/v1/me")
check("unib.ta", "existing session rejected immediately (no wait for next login)", r.status_code in (401, 403), r.status_code)
r = get(ta, f"https://{LMS}/courses/{UNIB}/courseware")
check("unib.ta", "existing session cannot reach the course", r.status_code != 200, r.status_code)
n = lms_shell(f"from edulage_platform.models import ManagedRole, SupportScope; from django.contrib.auth.models import User; u=User.objects.get(username={ta.lms_username!r}); "
              "from common.djangoapps.student.models import CourseAccessRole; print(ManagedRole.objects.filter(user=u).count()+CourseAccessRole.objects.filter(user=u).count())")
check("edulage-svc", "all managed roles revoked on suspension", n == "0", n)
r = svc.post(f"{API}/admissions/", json={"sub": ta_sub, "course_id": UNIB, "institution": "UNIB"}, timeout=60)
check("edulage-svc", "suspended user cannot be admitted (409)", r.status_code == 409, r.status_code)
try:
    sso_session("unib.ta")
    relogin = "logged in"
except RuntimeError:
    relogin = "refused"
check("unib.ta", "fresh SSO login refused while suspended", relogin == "refused", relogin)
r = svc.post(f"{API}/users/status/", json={"sub": ta_sub, "status": "active"}, timeout=60)
ta2 = sso_session("unib.ta")
check("unib.ta", "reactivation -> login works again", r.ok and bool(ta2.lms_username), ta2.lms_username)
check("audit", "suspended + reactivated audited", audit(ta_sub, "suspended") >= 1 and audit(ta_sub, "reactivated") >= 1, (audit(ta_sub, "suspended"), audit(ta_sub, "reactivated")))

# --- 7. shorter sessions for staff ----------------------------------------------------------
def session_ttl(s):
    c = next(c for c in s.cookies if c.name == "sessionid")
    return (c.expires or 0) - time.time()

get(unia_admin, f"https://{LMS}/api/user/v1/me")  # any request after login applies the staff clamp
check("unia.admin", "staff session expires within 1h", 0 < session_ttl(unia_admin) <= 3600, f"{session_ttl(unia_admin):.0f}s")
check("ada.learner", "learner session keeps the platform default (> 1h)", session_ttl(ada) > 3600, f"{session_ttl(ada):.0f}s")

print(f"\n{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
