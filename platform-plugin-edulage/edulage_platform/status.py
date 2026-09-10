"""
Branded account-status pages for outcomes Open edX would otherwise report with stock or
plain-text messages: refused account link, suspended account, admission not yet confirmed,
generic sign-in failure. Served by the LMS at ``/edulage/account/<code>/`` and rendered from a
self-contained template (fonts, logo and tokens from the brand package on the MFE host).
"""
from urllib.parse import urlencode

from django.conf import settings
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.utils.http import url_has_allowed_host_and_scheme

from .auth import REGISTER_PARAM

SITE_URL = "https://edulage.org"

PAGES = {
    "link-refused": {
        "status": 403,
        "eyebrow": "Sign-in not completed",
        "title": "We couldn't connect your EduLage account",
        "body": (
            "An account with this e-mail address already exists on the learning platform, but it "
            "could not be linked to your EduLage identity automatically. This happens when the "
            "e-mail address has not been verified, when more than one account shares it, or when "
            "the account is already connected to a different EduLage identity."
        ),
        "steps": [
            "Verify your e-mail address in your EduLage account, then sign in again.",
            "If you already have a learning account, contact learner support so we can connect it safely.",
        ],
        "primary": ("Contact learner support", f"{SITE_URL}/help"),
        "secondary": ("Try signing in again", "{login_url}"),
    },
    "suspended": {
        "status": 403,
        "eyebrow": "Account suspended",
        "title": "Your account has been suspended",
        "body": (
            "Access to My learning is currently suspended. If you believe this is a mistake, please "
            "contact your institution or EduLage learner support and quote the e-mail address you "
            "use with EduLage."
        ),
        "steps": [],
        "primary": ("Contact learner support", f"{SITE_URL}/help"),
        "secondary": ("Back to EduLage", SITE_URL),
    },
    "pending": {
        "status": 200,
        "eyebrow": "Admission required",
        "title": "This programme opens once the institution admits you",
        "body": (
            "Degrees and selective programmes on EduLage follow the institution's admission decision. "
            "Your account is active: open short courses can be joined straight away, and any "
            "applications you have made are tracked under Applications in My learning."
        ),
        "steps": [
            "Apply to the programme from its page on edulage.org if you have not done so yet.",
            "When the institution admits you, the programme unlocks in My learning automatically.",
        ],
        "primary": ("Go to My learning", "/dashboard"),
        "secondary": ("Browse programmes", f"{SITE_URL}/programmes"),
    },
    "sign-in-failed": {
        "status": 200,
        "eyebrow": "Sign-in not completed",
        "title": "We couldn't sign you in",
        "body": (
            "Something went wrong while connecting to EduLage. Your details were not changed. "
            "Please try again; if the problem continues, contact learner support."
        ),
        "steps": [],
        "primary": ("Try signing in again", "{login_url}"),
        "secondary": ("Contact learner support", f"{SITE_URL}/help"),
    },
}


def page_url(code):
    return f"/edulage/account/{code}/"


def _brand_url():
    return getattr(settings, "EDULAGE_BRAND_URL", "") or f"https://apps.{settings.LMS_BASE}/brand"


def _context(code, request=None):
    page = PAGES[code]
    login_url = settings.LOGIN_URL
    if request is not None and request.GET.get("next", "").startswith("/"):
        login_url = f"{login_url}?next={request.GET['next']}"

    def resolve(link):
        label, href = link
        return {"label": label, "href": href.replace("{login_url}", login_url)}

    return {
        "code": code,
        "page": page,
        "primary": resolve(page["primary"]),
        "secondary": resolve(page["secondary"]),
        "site_url": SITE_URL,
        "brand_url": _brand_url(),
        "platform_name": getattr(settings, "PLATFORM_NAME", "EduLage"),
        "support_email": getattr(settings, "CONTACT_EMAIL", ""),
    }


def render_status(request, code):
    return render(request, "edulage_platform/status.html", _context(code, request), status=PAGES[code]["status"])


@never_cache
def status_view(request, code):
    if code not in PAGES:
        raise Http404
    return render_status(request, code)


@never_cache
def register_view(request):
    """
    ``/edulage/register/`` — the "Create account" entry point linked from edulage.org and the LMS
    sign-in page. Starts the EduLage SSO flow at the IdP's registration form; after e-mail
    verification the learner lands on My Learning with a JIT-created LMS account.
    """
    if request.user.is_authenticated:
        return HttpResponseRedirect("/dashboard")
    nxt = request.GET.get("next", "/dashboard")
    if not url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}):
        nxt = "/dashboard"
    query = urlencode({"auth_entry": "login", "next": nxt, REGISTER_PARAM: "1"})
    return HttpResponseRedirect(f"/auth/login/edulage/?{query}")
