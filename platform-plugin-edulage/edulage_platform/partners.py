"""
Institution onboarding — a prospective institution asks to join from edulage.org
(``POST /edulage/api/v1/partner-requests/``); an EduLage administrator reviews it at
``/edulage/admin/partners/``. Approval provisions the institution in one step: the Open edX
organisation, the eox-tenant configuration and route for ``<code>.<LMS host>``, and a staff
invitation making the named contact the first institution administrator — from there the
institution console takes over. Nothing is created from the public form itself.

The tenant host is served as soon as the route exists: wildcard DNS points ``*.<LMS host>`` at the
proxy and Caddy issues its certificate on demand after asking the LMS whether the host is a tenant.
"""
import logging
import re
import secrets

from django.conf import settings
from django.contrib import messages
from django.db import transaction
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from . import emails, identity, keycloak
from .console import _login_redirect, _page_context
from .models import PartnerRequest, StaffInvitation

log = logging.getLogger(__name__)

ADMIN_PATH = "/edulage/admin/partners/"
CODE_RE = re.compile(r"^[A-Z][A-Z0-9]{1,15}$")
RESERVED_CODES = {"OPENEDX", "EDULAGE", "ADMIN", "API", "WWW", "LEARN", "STUDIO", "APPS", "AUTH"}


def suggest_code(name):
    words = re.findall(r"[A-Za-z0-9]+", name or "")
    code = "".join(w[0] for w in words if w[0].isalpha()).upper()
    if len(code) < 2:
        code = re.sub(r"[^A-Z0-9]", "", (name or "").upper())[:8]
    return code[:16]


def tenant_host(code):
    return f"{code.lower()}.{settings.LMS_BASE}"


def institution_page(code):
    """edulage.org profile page for an institution (the LMS tenant host's landing and course-list target)."""
    return f"/institutions/{code.lower()}"


def code_available(code):
    from organizations.models import Organization  # pylint: disable=import-outside-toplevel

    return CODE_RE.match(code) and code not in RESERVED_CODES and not Organization.objects.filter(short_name=code).exists()


def record_request(data):
    """Store a request from edulage.org and notify both sides; returns (request, created)."""
    email = data["contact_email"].strip().lower()
    existing = PartnerRequest.objects.filter(contact_email=email, status=PartnerRequest.STATUS_PENDING).first()
    if existing:
        return existing, False
    req = PartnerRequest.objects.create(
        institution_name=data["institution_name"].strip(),
        short_name=(data.get("short_name") or suggest_code(data["institution_name"])).strip().upper()[:16],
        country=(data.get("country") or "").strip(),
        website=(data.get("website") or "").strip(),
        contact_name=data["contact_name"].strip(),
        contact_email=email,
        contact_role=(data.get("contact_role") or "").strip(),
        message=(data.get("message") or "").strip(),
    )
    identity.audit("partner_requested", email=email, detail=f"{req.institution_name} (#{req.pk})", actor="site")
    details = [
        ("Institution", req.institution_name), ("Country", req.country), ("Website", req.website),
        ("Contact", f"{req.contact_name} <{req.contact_email}>"), ("Role", req.contact_role),
    ]
    emails.send_notice(
        [req.contact_email],
        "We received your request to bring your institution onto EduLage",
        "Partnership request", f"Thank you, {req.contact_name.split()[0]}",
        [
            f"We have received your request to bring {req.institution_name} onto EduLage and will review it shortly.",
            "Once approved, you will receive an invitation to become the institution's first administrator, "
            "from where you can invite your team and start publishing courses.",
        ],
        details,
        footnote="If you did not submit this request, you can ignore this e-mail.",
    )
    if settings.EDULAGE_PARTNERS_EMAIL:
        emails.send_notice(
            [settings.EDULAGE_PARTNERS_EMAIL],
            f"New institution request: {req.institution_name}",
            "For review", f"{req.institution_name} wants to join EduLage",
            [req.message or "No message was included."],
            details,
            action_url=f"https://{settings.LMS_BASE}{ADMIN_PATH}", action_label="Review request",
        )
    return req, True


def provision_institution(code, name, admin_user, request_obj=None):
    """
    Create the Open edX organisation, eox-tenant config/route and the first institution-admin
    invitation for ``code``. Idempotent on the tenant/org; returns the StaffInvitation.
    """
    from eox_tenant.models import Route, TenantConfig  # pylint: disable=import-outside-toplevel
    from organizations.models import Organization  # pylint: disable=import-outside-toplevel

    host = tenant_host(code)
    with transaction.atomic():
        # eox-tenant's save signal calls Organization.get_or_create(name=code, short_name=code), so the
        # organisation must carry the code as its name; the display name lives in the tenant config.
        tenant, _ = TenantConfig.objects.update_or_create(
            external_key=code.lower(),
            defaults={
                "lms_configs": {
                    "EDNX_USE_SIGNAL": True,
                    "SITE_NAME": host,
                    "LMS_BASE": host,
                    "LMS_ROOT_URL": f"https://{host}",
                    "PLATFORM_NAME": f"{name} on EduLage",
                    "platform_name": f"{name} on EduLage",
                    "course_org_filter": [code],
                    "EDULAGE_INSTITUTION": code,
                    "EDULAGE_INSTITUTION_NAME": name,
                    # "/" and "/courses" on the tenant host land on the institution's edulage.org page.
                    "MKTG_URLS": {**settings.MKTG_URLS, "ROOT": settings.MKTG_URLS["ROOT"] + institution_page(code), "COURSES": institution_page(code)},
                },
                "studio_configs": {},
                "theming_configs": {},
                "meta": {
                    "edulage_institution": code, "edulage_institution_name": name,
                    "website": request_obj.website if request_obj else "", "country": request_obj.country if request_obj else "",
                },
            },
        )
        Route.objects.update_or_create(domain=host, defaults={"config": tenant})
        Organization.objects.get_or_create(short_name=code, defaults={"name": code, "description": name, "active": True})
        Organization.objects.filter(short_name=code).update(description=name, active=True)
        contact_email = request_obj.contact_email if request_obj else None
        invitation = None
        if contact_email:
            invitation = StaffInvitation.objects.create(
                token=secrets.token_urlsafe(32), email=contact_email, institution=code,
                role="institution_admin", invited_by=admin_user,
            )
            identity.audit("invited", user=admin_user, email=contact_email, detail=f"{invitation.claim} by onboarding", actor="partners")
        if request_obj:
            request_obj.status = PartnerRequest.STATUS_APPROVED
            request_obj.short_name = code
            request_obj.institution_name = name
            request_obj.decided = timezone.now()
            request_obj.decided_by = admin_user
            request_obj.invitation = invitation
            request_obj.save()
        identity.audit("partner_approved", user=admin_user, email=contact_email or "", detail=f"{code}: {name}", actor="partners")
    return invitation


def _guard(request):
    if not request.user.is_authenticated:
        return _login_redirect(request)
    if not (request.user.is_superuser or request.user.is_staff):
        return HttpResponseForbidden("EduLage administrators only")
    return None


@never_cache
def admin_view(request):
    refused = _guard(request)
    if refused:
        return refused
    from organizations.models import Organization  # pylint: disable=import-outside-toplevel

    pending = list(PartnerRequest.objects.filter(status=PartnerRequest.STATUS_PENDING))
    for req in pending:
        req.suggested_code = req.short_name if code_available(req.short_name) else suggest_code(req.institution_name)
        req.code_taken = bool(req.short_name) and not code_available(req.short_name)
    context = _page_context(
        request,
        pending=pending,
        decided=PartnerRequest.objects.exclude(status=PartnerRequest.STATUS_PENDING).select_related("invitation")[:50],
        institutions=Organization.objects.filter(active=True).order_by("short_name"),
        idp_ready=keycloak.configured(),
        lms_host=settings.LMS_BASE,
        admin_url=ADMIN_PATH,
    )
    return render(request, "edulage_platform/partners.html", context)


@never_cache
@require_POST
def approve_view(request, pk):
    refused = _guard(request)
    if refused:
        return refused
    req = get_object_or_404(PartnerRequest, pk=pk, status=PartnerRequest.STATUS_PENDING)
    code = (request.POST.get("code") or "").strip().upper()
    name = (request.POST.get("name") or req.institution_name).strip()
    back = redirect("edulage:partners")
    if not name:
        messages.error(request, "The institution needs a display name.")
        return back
    if not code_available(code):
        messages.error(request, f"'{code}' is not usable as an institution code: use 2–16 capital letters/digits, not already in use.")
        return back
    if not keycloak.configured():
        messages.error(request, "Onboarding needs the identity provider configured (staff invitations are disabled).")
        return back
    invitation = provision_institution(code, name, request.user, req)
    accept_url = request.build_absolute_uri(f"/edulage/invite/{invitation.token}/")
    sent = emails.send_notice(
        [req.contact_email],
        f"{name} is approved on EduLage — set up your institution",
        "Approved", f"Welcome to EduLage, {name}",
        [
            f"{req.contact_name.split()[0]}, your request has been approved. {name} now exists on EduLage with the institution code {code}.",
            f"Accept the invitation below with an EduLage account registered to {req.contact_email} (sign in or create one) to become "
            "the institution's first administrator. From the institution console you can invite your course authors and tutors; "
            "courses are created in Studio.",
        ],
        [("Institution", name), ("Code", code), ("Institution console", f"https://{settings.LMS_BASE}/edulage/institution/{code}/"),
         ("Studio", settings.EDULAGE_STUDIO_URL)],
        action_url=accept_url, action_label="Accept invitation",
        footnote=f"The invitation is valid for {StaffInvitation.EXPIRY_DAYS} days. Staff accounts set up an authenticator app at first sign-in.",
    )
    if sent:
        messages.success(request, f"{name} ({code}) created; invitation sent to {req.contact_email}.")
    else:
        messages.warning(request, f"{name} ({code}) created, but the e-mail failed — share the invitation link: {accept_url}")
    return back


@never_cache
@require_POST
def decline_view(request, pk):
    refused = _guard(request)
    if refused:
        return refused
    req = get_object_or_404(PartnerRequest, pk=pk, status=PartnerRequest.STATUS_PENDING)
    reason = (request.POST.get("reason") or "").strip()
    req.status = PartnerRequest.STATUS_DECLINED
    req.note = reason
    req.decided = timezone.now()
    req.decided_by = request.user
    req.save(update_fields=["status", "note", "decided", "decided_by"])
    identity.audit("partner_declined", user=request.user, email=req.contact_email, detail=f"{req.institution_name}: {reason}", actor="partners")
    emails.send_notice(
        [req.contact_email],
        "Your EduLage partnership request",
        "Partnership request", f"About {req.institution_name} on EduLage",
        [
            f"Thank you for your interest in bringing {req.institution_name} onto EduLage. We are unable to proceed with the request at this time."
            + (f" Note from our team: {reason}" if reason else ""),
            "You are welcome to get in touch if circumstances change.",
        ],
        footnote=f"Questions? Write to {settings.EDULAGE_PARTNERS_EMAIL or getattr(settings, 'CONTACT_EMAIL', '')}.",
    )
    messages.success(request, f"Request from {req.institution_name} declined.")
    return redirect("edulage:partners")
