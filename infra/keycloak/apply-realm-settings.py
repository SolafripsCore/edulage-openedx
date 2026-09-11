#!/usr/bin/env python3
"""Apply the EduLage realm settings for open learner registration (idempotent).

edX/Coursera model: anyone creates an account first; admission (where a programme requires it)
comes later and only unlocks programme content. Keycloak therefore allows self-registration
with e-mail as the username, verifies the e-mail before the first LMS login, offers password
reset, and renders every page/e-mail with the `edulage` theme (themes/edulage).

Run on the host next to the Keycloak container (same env as enforce-staff-mfa.py):
  KC_URL=http://<container-ip>:8080 KC_ADMIN_PASSWORD=... infra/keycloak/apply-realm-settings.py
or, when the master admin has a pending required action (e.g. TOTP enrolment) and the password
grant answers "Account is not fully set up", with a temporary admin service account created by
`kc.sh bootstrap-admin service`:
  KC_URL=... KC_CLIENT_ID=<id> KC_CLIENT_SECRET=... infra/keycloak/apply-realm-settings.py
"""
import json
import os
import sys
import urllib.parse
import urllib.request

BASE = os.environ["KC_URL"].rstrip("/")
REALM = os.environ.get("KC_REALM", "edulage")

SETTINGS = {
    "displayName": "EduLage",
    "displayNameHtml": "EduLage",
    "loginTheme": "edulage",
    "emailTheme": "edulage",
    "registrationAllowed": True,
    "registrationEmailAsUsername": True,
    "loginWithEmailAllowed": True,
    "duplicateEmailsAllowed": False,
    "verifyEmail": True,
    "resetPasswordAllowed": True,
    "rememberMe": True,
    "editUsernameAllowed": False,
    "bruteForceProtected": True,
    "permanentLockout": False,
    "failureFactor": 10,
    "waitIncrementSeconds": 60,
    "maxFailureWaitSeconds": 900,
    "maxDeltaTimeSeconds": 43200,
    "passwordPolicy": "length(8) and notUsername(undefined) and notEmail(undefined)",
    "attributes": {
        "frontendUrl": "https://auth.edulage.org",
    },
}


def token():
    if os.environ.get("KC_CLIENT_SECRET"):
        form = {
            "client_id": os.environ["KC_CLIENT_ID"],
            "client_secret": os.environ["KC_CLIENT_SECRET"],
            "grant_type": "client_credentials",
        }
    else:
        form = {
            "client_id": "admin-cli",
            "grant_type": "password",
            "username": os.environ.get("KC_ADMIN_USER", "admin"),
            "password": os.environ["KC_ADMIN_PASSWORD"],
        }
    data = urllib.parse.urlencode(form).encode()
    with urllib.request.urlopen(f"{BASE}/realms/master/protocol/openid-connect/token", data) as r:
        return json.load(r)["access_token"]


TOKEN = token()


def call(method, path, body=None):
    req = urllib.request.Request(
        f"{BASE}/admin/realms/{REALM}{path}",
        data=None if body is None else json.dumps(body).encode(),
        method=method,
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req) as r:
            raw = r.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        sys.exit(f"{method} {path} -> {e.code} {e.read().decode()[:400]}")


realm = call("GET", "")
realm.update({k: v for k, v in SETTINGS.items() if k != "attributes"})
realm.setdefault("attributes", {}).update(SETTINGS["attributes"])
call("PUT", "", realm)

# User profile: e-mail is the username, so only first/last name are asked on the register form.
profile = call("GET", "/users/profile")
for attr in profile["attributes"]:
    if attr["name"] in ("firstName", "lastName", "email"):
        attr["required"] = {"roles": ["user"]}
        attr["permissions"] = {"view": ["admin", "user"], "edit": ["admin", "user"]}
# edulage_roles is written only by administrators / the LMS console service account, never by the user.
if not any(a["name"] == "edulage_roles" for a in profile["attributes"]):
    profile["attributes"].append({
        "name": "edulage_roles",
        "displayName": "EduLage roles",
        "multivalued": True,
        "permissions": {"view": ["admin"], "edit": ["admin"]},
        "validations": {"length": {"max": 255}},
    })
call("PUT", "/users/profile", profile)

realm = call("GET", "")
print(json.dumps({k: realm.get(k) for k in SETTINGS if k != "attributes"}, indent=1))
