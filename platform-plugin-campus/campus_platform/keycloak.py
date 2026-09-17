"""
Thin client for the identity provider's admin API (Keycloak), used by the institution
console to grant and revoke staff roles.

Roles live on the IdP as the multi-valued user attribute ``campus_roles`` (issued as the
``campus_roles`` claim at sign-in and mirrored onto Open edX by ``identity.apply_roles``); the
``campus-staff`` group carries the mandatory-MFA rule. Writing here rather than only to the LMS
keeps a single source of truth: the next sign-in reproduces exactly what the console set.

Authenticates as a confidential service-account client (``CAMPUS_KC_CLIENT_ID`` /
``CAMPUS_KC_CLIENT_SECRET``) that holds the realm-management roles ``view-users``,
``query-users``, ``manage-users`` and ``query-groups`` — see infra/keycloak/create-console-client.py.
"""
import logging

import requests
from django.conf import settings

from .identity import is_staff_claimset

log = logging.getLogger(__name__)

ROLES_ATTRIBUTE = "campus_roles"
STAFF_GROUP = "campus-staff"
TIMEOUT = 10


class KeycloakError(Exception):
    """The IdP refused or could not complete an admin operation."""


def configured():
    return bool(settings.CAMPUS_KC_URL and settings.CAMPUS_KC_CLIENT_ID and settings.CAMPUS_KC_CLIENT_SECRET)


def _base():
    return settings.CAMPUS_KC_URL.rstrip("/")


def _token():
    try:
        r = requests.post(
            f"{_base()}/realms/{settings.CAMPUS_KC_REALM}/protocol/openid-connect/token",
            data={
                "grant_type": "client_credentials",
                "client_id": settings.CAMPUS_KC_CLIENT_ID,
                "client_secret": settings.CAMPUS_KC_CLIENT_SECRET,
            },
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        return r.json()["access_token"]
    except (requests.RequestException, KeyError, ValueError) as exc:
        raise KeycloakError("identity provider unavailable") from exc


def _call(method, path, body=None, params=None):
    if not configured():
        raise KeycloakError("identity provider not configured")
    url = f"{_base()}/admin/realms/{settings.CAMPUS_KC_REALM}{path}"
    try:
        r = requests.request(
            method, url, json=body, params=params, timeout=TIMEOUT,
            headers={"Authorization": f"Bearer {_token()}"},
        )
    except requests.RequestException as exc:
        raise KeycloakError("identity provider unavailable") from exc
    if r.status_code == 404:
        return None
    if r.status_code >= 400:
        log.error("campus: keycloak %s %s -> %s %s", method, path, r.status_code, r.text[:200])
        raise KeycloakError(f"identity provider returned {r.status_code}")
    return r.json() if r.content else {}


def get_user(sub):
    """Keycloak user representation for a control-plane account id, or None."""
    return _call("GET", f"/users/{sub}")


def find_user_by_email(email):
    # The list endpoint omits attributes unless briefRepresentation is off.
    users = _call(
        "GET", "/users",
        params={"email": email, "exact": "true", "briefRepresentation": "false"},
    ) or []
    return users[0] if users else None


def roles_of(kc_user):
    return list((kc_user.get("attributes") or {}).get(ROLES_ATTRIBUTE) or [])


def _staff_group_id():
    groups = _call("GET", "/groups", params={"search": STAFF_GROUP, "exact": "true"}) or []
    for g in groups:
        if g["name"] == STAFF_GROUP:
            return g["id"]
    raise KeycloakError(f"group {STAFF_GROUP} missing on the identity provider")


def set_roles(kc_user, roles):
    """Replace the account's ``campus_roles`` and align ``campus-staff`` membership (MFA)."""
    roles = sorted(set(roles)) or ["learner"]
    attributes = dict(kc_user.get("attributes") or {})
    attributes[ROLES_ATTRIBUTE] = roles
    # User-profile validation runs on the whole representation, so send it back complete.
    _call("PUT", f"/users/{kc_user['id']}", body={**kc_user, "attributes": attributes})
    gid = _staff_group_id()
    if is_staff_claimset(roles):
        _call("PUT", f"/users/{kc_user['id']}/groups/{gid}")
    else:
        _call("DELETE", f"/users/{kc_user['id']}/groups/{gid}")
    return roles
