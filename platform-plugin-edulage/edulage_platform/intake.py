"""
Screening of the public "Register your institution" request (``POST /edulage/api/v1/partner-requests/``),
which e-mails a confirmation to the submitted address. Kept free of Open edX imports so it can be
unit-tested with plain Django; ``record`` is ``partners.record_request``.
"""
import re

from . import botguard

HONEYPOT_FIELD = "company"
TOKEN_FIELD = "form_token"
REQUIRED = ("institution_name", "contact_name", "contact_email")
LIMITS = {
    "institution_name": 160, "short_name": 16, "country": 80, "website": 200, "contact_name": 120,
    "contact_email": 254, "contact_role": 120, "message": 4000,
}
CODE_RE = re.compile(r"^[A-Z][A-Z0-9]{1,15}$")
EMAIL_RE = re.compile(r"^[^@\s<>\"',;]+@[^@\s<>\"',;]+\.[^@\s<>\"',;.]{2,}$")

# (scope, limit, window seconds); the per-IP hourly limit is the DRF throttle on the view.
PER_IP_DAY = ("partner-ip-day", 10, 24 * 3600)
PER_EMAIL_DAY = ("partner-email-day", 3, 24 * 3600)
GLOBAL_HOUR = ("partner-global-hour", 30, 3600)

ACCEPTED = 202
FAKE_SUCCESS = (ACCEPTED, {"status": "received"})


def partner_request(data, ip, record):
    """Returns ``(http_status, body)``; ``record(clean)`` is only reached by submissions that pass every check."""
    data = data if isinstance(data, dict) else {}
    if str(data.get(HONEYPOT_FIELD) or "").strip():
        return FAKE_SUCCESS
    token = botguard.check_form_token(data.get(TOKEN_FIELD))
    if token == botguard.TOKEN_TOO_FAST:
        return FAKE_SUCCESS
    if token != botguard.TOKEN_OK:
        return 400, {"error": token, "fields": []}

    clean = {k: str(data.get(k) or "").strip() for k in LIMITS}
    problems = [k for k in REQUIRED if not clean[k]] + [k for k, v in clean.items() if len(v) > LIMITS[k]]
    if not EMAIL_RE.match(clean["contact_email"]):
        problems.append("contact_email")
    if clean["contact_name"] and botguard.suspicious_person_name(clean["contact_name"], LIMITS["contact_name"]):
        problems.append("contact_name")
    for field in ("institution_name", "country", "contact_role"):
        if botguard.suspicious_text(clean[field], LIMITS[field]):
            problems.append(field)
    if clean["website"] and not clean["website"].startswith(("http://", "https://")):
        clean["website"] = "https://" + clean["website"]
    if clean["short_name"] and not CODE_RE.match(clean["short_name"].upper()):
        problems.append("short_name")
    if problems:
        return 400, {"error": "invalid", "fields": sorted(set(problems))}

    email = clean["contact_email"].lower()
    if not botguard.within_limits(
        (PER_IP_DAY[0], ip or "unknown", PER_IP_DAY[1], PER_IP_DAY[2]),
        (PER_EMAIL_DAY[0], email, PER_EMAIL_DAY[1], PER_EMAIL_DAY[2]),
        (GLOBAL_HOUR[0], "all", GLOBAL_HOUR[1], GLOBAL_HOUR[2]),
    ):
        return 429, {"error": "rate_limited"}

    req, created = record(clean)
    return ACCEPTED, {"status": "received" if created else "already_pending", "id": req.pk}
