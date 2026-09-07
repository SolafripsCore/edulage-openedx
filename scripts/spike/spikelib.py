"""Shared helpers for the browser-less spike checks (SSO session, Studio SSO, request wrappers)."""
import html
import os
import re

import requests

LMS = os.environ.get("LMS_HOST", "learn.edulage.org")
CMS = os.environ.get("CMS_HOST", "studio.edulage.org")
PASSWORD = os.environ.get("SPIKE_TEST_PASSWORD", "")


def sso_session(idp_username, host=LMS):
    """Log into the LMS through the EduLage IdP; returns an authenticated requests.Session."""
    s = requests.Session()
    s.headers["User-Agent"] = "edulage-spike/1.0"
    r = s.get(f"https://{host}/auth/login/edulage/?auth_entry=login&next=/dashboard", timeout=60)
    m = re.search(r'<form[^>]+id="kc-form-login"[^>]+action="([^"]+)"', r.text)
    if not m:
        raise RuntimeError(f"IdP login form not found at {r.url}")
    r = s.post(html.unescape(m.group(1)), data={"username": idp_username, "password": PASSWORD}, timeout=60)
    if "kc-form-login" in r.text:
        raise RuntimeError(f"IdP rejected credentials for {idp_username}")
    if r.url.endswith("/authn/register"):
        # first login: emulate the authn MFE auto-submitting the registration form
        d = s.get(f"https://{host}/api/mfe_context?next=/dashboard", timeout=60).json()["contextData"]["pipelineUserDetails"]
        csrf = s.get(f"https://{host}/csrf/api/v1/token", timeout=60).json()["csrfToken"]
        s.post(
            f"https://{host}/api/user/v1/account/registration/",
            data={"username": d["username"], "email": d["email"], "name": d["name"],
                  "honor_code": "true", "terms_of_service": "true", "social_auth_provider": "EduLage"},
            headers={"X-CSRFToken": csrf, "Referer": f"https://{host}/"},
            timeout=60,
        )
        s.get(f"https://{host}/auth/complete/edulage/", timeout=60)
    me = s.get(f"https://{host}/api/user/v1/me", timeout=60)
    if not me.ok:
        raise RuntimeError(f"LMS session not established for {idp_username}: {me.status_code}")
    s.lms_username = me.json()["username"]
    return s


def studio_login(s):
    """Studio authenticates against the LMS via OAuth2 (SSO, no second credential prompt)."""
    r = s.get(f"https://{CMS}/login/", timeout=60)
    return r.url


def get(s, url, **kw):
    return s.get(url, timeout=60, allow_redirects=False, **kw)


def status(s, url):
    r = s.get(url, timeout=60, allow_redirects=False)
    return r.status_code, r.headers.get("Location", "")[:100], r
