"""
Bot protection for public forms that make the platform send e-mail (Django-only, no Open edX imports).

All EduLage products share one Resend account: a bot that pushes spam text through a public form into
a confirmation e-mail addressed to a third party burns the quota for every product. Every public
e-mail trigger therefore goes through, in order and before any database write or send:

1. honeypot   — a hidden field real visitors never fill → fake success, nothing stored or sent;
2. form token — signed render-time token (``issue_form_token``): < ``MIN_FILL_SECONDS`` old → fake
                success; missing/tampered/older than ``MAX_FORM_AGE_SECONDS`` → rejected;
3. validation — names may not contain links, domains, ``@``, digits/symbols or random mixed-case strings;
4. rate limit — per client IP, per target e-mail and a global cap (Django cache, fixed window).
"""
import hashlib
import re
import time
import unicodedata

from django.core import signing
from django.core.cache import cache

MIN_FILL_SECONDS = 3
MAX_FORM_AGE_SECONDS = 12 * 3600
TOKEN_SALT = "edulage.botguard.form"

TOKEN_OK, TOKEN_TOO_FAST, TOKEN_EXPIRED, TOKEN_INVALID = "ok", "too_fast", "expired", "invalid"

URL_RE = re.compile(r"(https?:|ftp:|www\.|://|\bbit\.ly\b|\bt\.me\b)", re.IGNORECASE)
DOMAIN_RE = re.compile(r"[^\W\d_]{2,}\.(?:[a-z]{2,24})(?![^\W\d_])", re.IGNORECASE)
# Besides letters (any script) and combining accents, the joiners real names use.
NAME_JOINERS = set(" '’.-")
# Organisation names/roles may also use digits and common punctuation, but never links or markup.
ORG_TEXT_FORBIDDEN_RE = re.compile(r"[<>@{}\[\]\\|^~`$%*=+#]")


def _normalise(value):
    return unicodedata.normalize("NFC", str(value or "")).strip()


def _case_switches(word):
    switches, previous = 0, None
    for ch in word:
        if not ch.isalpha() or not ch.isascii():
            continue
        current = ch.isupper()
        if previous is not None and current != previous:
            switches += 1
        previous = current
    return switches


def looks_random(word):
    """Bot-generated tokens such as ``hSJEcmPHCVTponlBiizsCzEX``: long and flipping case repeatedly."""
    letters = [ch for ch in word if ch.isalpha()]
    return len(letters) >= 12 and _case_switches(word) >= 5


def contains_link(value):
    value = _normalise(value)
    return bool(URL_RE.search(value) or DOMAIN_RE.search(value))


def suspicious_person_name(value, max_length=120):
    """True when ``value`` cannot be a person's name (O'Neill, Jean-Luc, José María, Nnamdi Jr., Ọlá pass)."""
    name = _normalise(value)
    if not name or len(name) > max_length or "@" in name or contains_link(name):
        return True
    if not unicodedata.category(name[0]).startswith("L"):
        return True
    if any(not unicodedata.category(ch).startswith(("L", "M")) and ch not in NAME_JOINERS for ch in name):
        return True
    return any(looks_random(word) for word in name.split())


def suspicious_text(value, max_length=200):
    """For short free-text labels shown in e-mails (institution, role, country): no links, markup or bot strings."""
    text = _normalise(value)
    if not text:
        return False
    if len(text) > max_length or contains_link(text) or ORG_TEXT_FORBIDDEN_RE.search(text):
        return True
    return any(looks_random(word) for word in text.split())


def issue_form_token(now=None):
    return signing.dumps({"t": int(now if now is not None else time.time())}, salt=TOKEN_SALT, compress=True)


def check_form_token(token, now=None):
    if not token or not isinstance(token, str):
        return TOKEN_INVALID
    try:
        issued = int(signing.loads(token, salt=TOKEN_SALT)["t"])
    except (signing.BadSignature, KeyError, TypeError, ValueError):
        return TOKEN_INVALID
    age = (now if now is not None else time.time()) - issued
    if age < MIN_FILL_SECONDS:
        return TOKEN_TOO_FAST
    if age > MAX_FORM_AGE_SECONDS:
        return TOKEN_EXPIRED
    return TOKEN_OK


def _key(scope, value):
    digest = hashlib.sha256(str(value).strip().lower().encode()).hexdigest()[:32]
    return f"edulage:botguard:{scope}:{digest}"


def hit(scope, value, limit, window_seconds):
    """Count one attempt for ``(scope, value)``; False once ``limit`` attempts were made in the window."""
    key = _key(scope, value)
    if cache.add(key, 1, timeout=window_seconds):
        return True
    try:
        count = cache.incr(key)
    except ValueError:  # expired between add() and incr()
        cache.add(key, 1, timeout=window_seconds)
        return True
    return count <= limit


def within_limits(*limits):
    """``limits`` are ``(scope, value, limit, window_seconds)``; every counter is charged, all must pass."""
    results = [hit(*limit) for limit in limits]
    return all(results)


def client_ip(request):
    try:
        from edx_django_utils.ip import get_safest_client_ip  # pylint: disable=import-outside-toplevel

        return get_safest_client_ip(request)
    except Exception:  # pylint: disable=broad-except
        return request.META.get("REMOTE_ADDR", "")


# Keycloak user-profile ``pattern`` validator for firstName/lastName (infra/keycloak/apply-realm-settings.py).
# Java- and Python-compatible: no links/domains/@/digits, no word with 3+ lower→upper flips (random strings).
KEYCLOAK_NAME_PATTERN = (
    r"^(?!.*(?:(?i:https?:|www\.)|@|[0-9]))"
    r"(?!.*[A-Za-z]{2,}\.[A-Za-z]{2,})"
    r"(?!.*[^\s]*[a-z][A-Z][^\s]*[a-z][A-Z][^\s]*[a-z][A-Z]).*$"
)

# Direct (non-SSO) LMS registrations: (scope, limit, window seconds).
REGISTRATION_PER_IP = ("register-ip-hour", 5, 3600)
REGISTRATION_PER_EMAIL = ("register-email-day", 3, 24 * 3600)
REGISTRATION_GLOBAL = ("register-global-hour", 100, 3600)


def registration_refusal(name, email, ip, sso_running, require_sso):
    """
    Decision for an LMS account registration (``StudentRegistrationRequested`` filter):
    ``None`` to allow, else ``(http_status, message)``. Learners register through the EduLage IdP,
    which verifies the e-mail first; direct API registrations are refused when ``require_sso``.
    """
    if require_sso and not sso_running:
        return 403, "Create your EduLage account from the EduLage sign-in page."
    if suspicious_person_name(name, 255):
        return 400, "Enter your full name using letters only (no links, numbers or symbols)."
    if sso_running:
        return None
    if not within_limits(
        (REGISTRATION_PER_IP[0], ip or "unknown", REGISTRATION_PER_IP[1], REGISTRATION_PER_IP[2]),
        (REGISTRATION_PER_EMAIL[0], email or "", REGISTRATION_PER_EMAIL[1], REGISTRATION_PER_EMAIL[2]),
        (REGISTRATION_GLOBAL[0], "all", REGISTRATION_GLOBAL[1], REGISTRATION_GLOBAL[2]),
    ):
        return 429, "Too many sign-up attempts. Please try again later."
    return None
