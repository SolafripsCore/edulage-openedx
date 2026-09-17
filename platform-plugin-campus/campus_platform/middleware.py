"""
Request-time enforcement that Open edX does not provide on its own:

* a suspended account (``is_active=False``) is refused on every request, including requests
  authenticated by the ``edx-jwt-cookie`` pair, which ``JwtAuthentication`` accepts for inactive
  users until the cookie expires; the cookies are cleared on the way out;
* sessions flagged as staff at SSO time are clamped to ``CAMPUS_STAFF_SESSION_SECONDS`` (idle
  timeout) after Open edX's login view has set its own multi-week expiry;
* the LMS's own sign-in/registration pages (``/login``, ``/register`` and their aliases, which
  otherwise forward to the authn MFE form with a "Sign in with {PLATFORM_NAME}" button) send anonymous
  visitors straight to the control-plane IdP, so there is one sign-in page for learners, institution
  staff and platform admins alike. Studio reaches the same path via its LMS OAuth2 hop.
  ``?el_password=1`` keeps the stock form reachable for the platform superuser;
* stock "Page not found" / "Server error" pages (Open edX branding, marketing navigation) are
  replaced by the branded status pages for HTML requests.

Installed after ``AuthenticationMiddleware`` and before the view (see settings.common).
"""
import base64
import json
import logging
from urllib.parse import urlencode

from django.conf import settings
from django.contrib.auth import get_user_model
from django.http import HttpResponseForbidden, HttpResponseRedirect
from django.utils.http import url_has_allowed_host_and_scheme

from .auth import REGISTER_PARAM
from .status import render_status

log = logging.getLogger(__name__)
User = get_user_model()

STAFF_SESSION_KEY = "campus_staff"
PASSWORD_LOGIN_PARAM = "el_password"
LOGIN_PATHS = {"/login", "/signin"}
REGISTER_PATHS = {"/register", "/signup", "/create_account"}
ERROR_PAGES = {404: "not-found", 500: "error"}
STOCK_PAGE_MARKER = b"openedx-release-line"


def _pipeline_running(request):
    """True while a third-party-auth (partial) pipeline is in progress for this session."""
    session = getattr(request, "session", None)
    return bool(session and (session.get("partial_pipeline_token") or session.get("partial_pipeline_token_")))


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


def _wants_html(request):
    if request.path.startswith("/api/") or request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return False
    accept = request.headers.get("Accept", "")
    return "text/html" in accept or "*/*" in accept or not accept


class AccountStatusMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        refused = self._refuse_if_suspended(request)
        if refused is not None:
            return refused
        sso = self._single_sign_in(request)
        if sso is not None:
            return sso
        response = self.get_response(request)
        self._clamp_staff_session(request)
        return self._brand_error_page(request, response)

    def _brand_error_page(self, request, response):
        if response.status_code not in ERROR_PAGES or not _wants_html(request):
            return response
        if not response.get("Content-Type", "").startswith("text/html") or response.streaming:
            return response
        if STOCK_PAGE_MARKER not in response.content:
            return response
        return render_status(request, ERROR_PAGES[response.status_code])

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
        if _wants_html(request):
            response = render_status(request, "suspended")
        else:
            response = HttpResponseForbidden("Your account has been suspended.")
        for name in _jwt_cookie_names():
            response.delete_cookie(name, domain=settings.SESSION_COOKIE_DOMAIN or None)
        return response

    def _single_sign_in(self, request):
        if settings.SERVICE_VARIANT != "lms" or request.method != "GET" or request.user.is_authenticated:
            return None
        path = request.path.rstrip("/") or "/"
        if path in LOGIN_PATHS:
            register = False
        elif path in REGISTER_PATHS:
            register = True
        else:
            return None
        if request.GET.get(PASSWORD_LOGIN_PARAM) == "1" or not settings.FEATURES.get("ENABLE_THIRD_PARTY_AUTH"):
            return None
        if _pipeline_running(request):
            # Mid-SSO hop (e.g. first sign-in: ``ensure_user_information`` sends the new identity to
            # ``/register`` to create the account) — let the LMS forward to the authn MFE.
            return None
        nxt = request.GET.get("next", "/dashboard")
        if not url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}):
            nxt = "/dashboard"
        query = {"auth_entry": "login", "next": nxt}
        if register:
            query[REGISTER_PARAM] = "1"
        return HttpResponseRedirect(f"/auth/login/campus/?{urlencode(query)}")

    def _clamp_staff_session(self, request):
        session = getattr(request, "session", None)
        if session is None or not session.get(STAFF_SESSION_KEY):
            return
        ttl = settings.CAMPUS_STAFF_SESSION_SECONDS
        if session.get_expiry_age() > ttl:
            session.set_expiry(ttl)
