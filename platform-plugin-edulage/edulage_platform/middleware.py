"""
Request-time enforcement that Open edX does not provide on its own:

* a suspended account (``is_active=False``) is refused on every request, including requests
  authenticated by the ``edx-jwt-cookie`` pair, which ``JwtAuthentication`` accepts for inactive
  users until the cookie expires; the cookies are cleared on the way out;
* sessions flagged as staff at SSO time are clamped to ``EDULAGE_STAFF_SESSION_SECONDS`` (idle
  timeout) after Open edX's login view has set its own multi-week expiry.

Installed after ``AuthenticationMiddleware`` and before the view (see settings.common).
"""
import base64
import json
import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.http import HttpResponseForbidden

log = logging.getLogger(__name__)
User = get_user_model()

STAFF_SESSION_KEY = "edulage_staff"


def _jwt_cookie_names():
    jwt = settings.JWT_AUTH
    return jwt.get("JWT_AUTH_COOKIE_HEADER_PAYLOAD", "edx-jwt-cookie-header-payload"), jwt.get(
        "JWT_AUTH_COOKIE_SIGNATURE", "edx-jwt-cookie-signature"
    )


def _username_from_jwt_cookie(request):
    """Unverified read of the JWT cookie payload; only used to *deny*, never to grant."""
    header_payload, _ = _jwt_cookie_names()
    raw = request.COOKIES.get(header_payload)
    if not raw or "." not in raw:
        return None
    payload = raw.split(".")[1]
    try:
        data = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (ValueError, json.JSONDecodeError):
        return None
    return data.get("preferred_username") or data.get("username")


class AccountStatusMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        refused = self._refuse_if_suspended(request)
        if refused is not None:
            return refused
        response = self.get_response(request)
        self._clamp_staff_session(request)
        return response

    def _refuse_if_suspended(self, request):
        user = request.user
        if user.is_authenticated:
            if user.is_active:
                return None
            request.session.flush()
        else:
            username = _username_from_jwt_cookie(request)
            if not username or User.objects.filter(username=username, is_active=True).exists():
                return None
        response = HttpResponseForbidden("Your account has been suspended.")
        for name in _jwt_cookie_names():
            response.delete_cookie(name, domain=settings.SESSION_COOKIE_DOMAIN or None)
        return response

    def _clamp_staff_session(self, request):
        session = getattr(request, "session", None)
        if session is None or not session.get(STAFF_SESSION_KEY):
            return
        ttl = settings.EDULAGE_STAFF_SESSION_SECONDS
        if session.get_expiry_age() > ttl:
            session.set_expiry(ttl)
