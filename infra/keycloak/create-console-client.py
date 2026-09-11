#!/usr/bin/env python3
"""Create the confidential service-account client the LMS institution console uses (idempotent).

The client ``edulage-lms-console`` gets the realm-management roles needed to read users, edit the
``edulage_roles`` attribute and manage ``edulage-staff`` group membership — nothing more. Prints
the client secret once; store it with
  tutor config save --set EDULAGE_KC_CLIENT_SECRET=<secret> && tutor local do init --limit=lms   (or restart lms)

Run on the host next to the Keycloak container:
  KC_URL=http://<container-ip>:8080 KC_ADMIN_PASSWORD=... infra/keycloak/create-console-client.py
"""
import json
import os
import sys
import urllib.parse
import urllib.request

BASE = os.environ["KC_URL"].rstrip("/")
REALM = os.environ.get("KC_REALM", "edulage")
CLIENT_ID = os.environ.get("KC_CONSOLE_CLIENT", "edulage-lms-console")
ROLES = ("view-users", "query-users", "manage-users", "query-groups")


def token():
    data = urllib.parse.urlencode(
        {
            "client_id": "admin-cli",
            "grant_type": "password",
            "username": os.environ.get("KC_ADMIN_USER", "admin"),
            "password": os.environ["KC_ADMIN_PASSWORD"],
        }
    ).encode()
    with urllib.request.urlopen(f"{BASE}/realms/master/protocol/openid-connect/token", data) as r:
        return json.load(r)["access_token"]


TOKEN = token()


def call(method, path, body=None, ok=(200, 201, 204)):
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
        if e.code in ok:
            return None
        sys.exit(f"{method} {path} -> {e.code} {e.read().decode()}")


clients = call("GET", f"/clients?clientId={CLIENT_ID}")
if not clients:
    call(
        "POST",
        "/clients",
        {
            "clientId": CLIENT_ID,
            "name": "EduLage LMS institution console",
            "description": "Service account: grants/revokes staff roles from the institution console",
            "protocol": "openid-connect",
            "publicClient": False,
            "serviceAccountsEnabled": True,
            "standardFlowEnabled": False,
            "directAccessGrantsEnabled": False,
            "implicitFlowEnabled": False,
        },
    )
    clients = call("GET", f"/clients?clientId={CLIENT_ID}")
client = clients[0]

service_user = call("GET", f"/clients/{client['id']}/service-account-user")
rm_client = call("GET", "/clients?clientId=realm-management")[0]
available = {r["name"]: r for r in call("GET", f"/clients/{rm_client['id']}/roles")}
call(
    "POST",
    f"/users/{service_user['id']}/role-mappings/clients/{rm_client['id']}",
    [available[name] for name in ROLES],
)

secret = call("GET", f"/clients/{client['id']}/client-secret")["value"]
print(f"{CLIENT_ID} ready with realm-management roles {', '.join(ROLES)}")
print(f"EDULAGE_KC_CLIENT_SECRET={secret}")
