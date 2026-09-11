"""Drive the LMS -> EduLage IdP (Keycloak stand-in) -> LMS OIDC login from the command line.

Usage: SPIKE_TEST_PASSWORD=... python scripts/spike/sso_login.py <idp-username> [lms-host]

Prints the resulting LMS identity (GET /api/user/v1/me) and the user's course roles so the
role-claim -> CourseAccessRole sync can be verified without a browser.
"""
import html
import os
import re
import sys

import requests

username = sys.argv[1]
host = sys.argv[2] if len(sys.argv) > 2 else "learn.edulage.org"
password = os.environ["SPIKE_TEST_PASSWORD"]

s = requests.Session()
s.headers["User-Agent"] = "edulage-spike/1.0"
r = s.get(f"https://{host}/auth/login/edulage/?auth_entry=login&next=/dashboard", timeout=60)
if "openid-connect/auth" not in r.url and "auth.edulage.org" not in r.url:
    sys.exit(f"expected IdP redirect, landed on {r.url} ({r.status_code})")

m = re.search(r'<form[^>]+id="kc-form-login"[^>]+action="([^"]+)"', r.text)
if not m:
    sys.exit("IdP login form not found")
r = s.post(html.unescape(m.group(1)), data={"username": username, "password": password}, timeout=60)
print("final url:", r.url, r.status_code)
if "kc-form-login" in r.text:
    sys.exit("IdP rejected credentials")

if r.url.endswith("/authn/register"):
    # First SSO login: the authn MFE auto-submits the registration form from the pipeline's
    # user details (skip_registration_form). Emulate that submit for a browser-less proof.
    ctx = s.get(f"https://{host}/api/mfe_context?next=/dashboard", timeout=60).json()["contextData"]
    d = ctx["pipelineUserDetails"]
    csrf = s.get(f"https://{host}/csrf/api/v1/token", timeout=60).json()["csrfToken"]
    reg = s.post(
        f"https://{host}/api/user/v1/account/registration/",
        data={"username": d["username"], "email": d["email"], "name": d["name"],
              "honor_code": "true", "terms_of_service": "true", "social_auth_provider": "EduLage"},
        headers={"X-CSRFToken": csrf, "Referer": f"https://{host}/"},
        timeout=60,
    )
    print("jit registration:", reg.status_code, reg.text[:200])
    s.get(f"https://{host}/auth/complete/edulage/", timeout=60)

me = s.get(f"https://{host}/api/user/v1/me", timeout=60)
print("lms identity:", me.status_code, me.text[:200])
if me.ok:
    acct = s.get(f"https://{host}/api/user/v1/accounts/{me.json()['username']}", timeout=60).json()
    print("email:", acct.get("email"), "is_active:", acct.get("is_active"))
    roles = s.get(f"https://{host}/api/enrollment/v1/roles/", timeout=60)
    print("course roles:", roles.status_code, roles.text[:400])
    dash = s.get(f"https://{host}/dashboard", timeout=60)
    print("dashboard:", dash.status_code, "logged in" if "Sign out" in dash.text or "Dashboard" in dash.text else "?")
    # secure logout: LMS logout must bounce to the IdP end-session endpoint
    out = s.get(f"https://{host}/logout", timeout=60, allow_redirects=False)
    print("logout:", out.status_code, out.headers.get("Location", "")[:120])
    me2 = s.get(f"https://{host}/api/user/v1/me", timeout=60)
    print("after logout:", me2.status_code)
