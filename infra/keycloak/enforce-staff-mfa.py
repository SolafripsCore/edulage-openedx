#!/usr/bin/env python3
"""Enforce TOTP for staff on the `edulage` realm (idempotent).

Members of the `edulage-staff` group get the realm role `mfa-required`; the browser flow
`browser-staff-mfa` (copy of the built-in `browser`) replaces "OTP if configured" with
"OTP required when the user has `mfa-required`", so staff without an authenticator are forced
to enrol one at their next sign-in. Learners are unaffected.

Run on the host next to the Keycloak container:
  KC_URL=http://<container-ip>:8080 KC_ADMIN_PASSWORD=... infra/keycloak/enforce-staff-mfa.py
"""
import json
import os
import sys
import urllib.parse
import urllib.request

BASE = os.environ["KC_URL"].rstrip("/")
REALM = os.environ.get("KC_REALM", "edulage")
ROLE = "mfa-required"
GROUP = "edulage-staff"
FLOW = "browser-staff-mfa"


def token():
    data = urllib.parse.urlencode(
        {
            "client_id": "admin-cli",
            "grant_type": "password",
            "username": os.environ.get("KC_ADMIN_USER", "admin"),
            "password": os.environ["KC_ADMIN_PASSWORD"],
        }
    ).encode()
    with urllib.request.urlopen(
        f"{BASE}/realms/master/protocol/openid-connect/token", data
    ) as r:
        return json.load(r)["access_token"]


TOKEN = token()


def call(method, path, body=None, ok=(200, 201, 204)):
    req = urllib.request.Request(
        f"{BASE}/admin/realms/{REALM}{path}",
        data=None if body is None else json.dumps(body).encode(),
        method=method,
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req) as r:
            raw = r.read()
            if r.status not in ok:
                sys.exit(f"{method} {path} -> {r.status}")
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        if e.code in ok:
            return None
        sys.exit(f"{method} {path} -> {e.code} {e.read().decode()}")


# 1. role + group mapping
if not [r for r in call("GET", "/roles") if r["name"] == ROLE]:
    call("POST", "/roles", {"name": ROLE, "description": "TOTP enforced at sign-in"})
role = call("GET", f"/roles/{ROLE}")
group = next(g for g in call("GET", "/groups") if g["name"] == GROUP)
call("POST", f"/groups/{group['id']}/role-mappings/realm", [role])

# 2. flow
flows = {f["alias"]: f for f in call("GET", "/authentication/flows")}
if FLOW not in flows:
    call("POST", "/authentication/flows/browser/copy", {"newName": FLOW}, ok=(201,))
execs = call("GET", f"/authentication/flows/{FLOW}/executions")
otp_sub = next(
    e
    for e in execs
    if e.get("authenticationFlow")
    and e["displayName"].endswith(("Conditional OTP", "Conditional 2FA"))
)
otp_alias = otp_sub["displayName"]
# children of the 2FA sub-flow follow it in the list at a deeper level until the level drops
children = []
seen = False
for e in execs:
    if e["id"] == otp_sub["id"]:
        seen = True
        continue
    if seen:
        if e["level"] <= otp_sub["level"]:
            break
        children.append(e)

for c in children:
    if c.get("providerId") in ("conditional-user-configured", "conditional-credential"):
        call("DELETE", f"/authentication/executions/{c['id']}")
if not any(c.get("providerId") == "conditional-user-role" for c in children):
    call(
        "POST",
        f"/authentication/flows/{urllib.parse.quote(otp_alias)}/executions/execution",
        {"provider": "conditional-user-role"},
        ok=(201,),
    )
execs = call("GET", f"/authentication/flows/{FLOW}/executions")
for e in execs:
    if e.get("providerId") == "conditional-user-role" and not e.get("authenticationConfig"):
        call(
            "POST",
            f"/authentication/executions/{e['id']}/config",
            {
                "alias": f"{FLOW}-staff-role",
                "config": {"condUserRole": ROLE, "negate": "false"},
            },
            ok=(201,),
        )
    elif e.get("providerId") == "conditional-user-role":
        cfg = call("GET", f"/authentication/config/{e['authenticationConfig']}")
        cfg["config"] = {"condUserRole": ROLE, "negate": "false"}
        call("PUT", f"/authentication/config/{cfg['id']}", cfg)
    if e.get("providerId") in ("conditional-user-role", "auth-otp-form"):
        e["requirement"] = "REQUIRED"
        call("PUT", f"/authentication/flows/{FLOW}/executions", e)

# 3. bind
call("PUT", "", {**call("GET", ""), "browserFlow": FLOW})

execs = call("GET", f"/authentication/flows/{FLOW}/executions")
print(f"browserFlow={call('GET', '')['browserFlow']}")
for e in execs:
    print("  " * e["level"], e.get("displayName"), e["requirement"], e.get("providerId", ""))
