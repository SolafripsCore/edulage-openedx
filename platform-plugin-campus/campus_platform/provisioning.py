"""
Institution (tenant) provisioning — the one place that turns an institution code and display
name into an Open edX ``Organization`` plus eox-tenant ``TenantConfig``/``Route``.

Host and platform-name shapes are settings so each product chooses its own convention:

    CAMPUS_TENANT_HOST_TEMPLATE      "{code}.{lms_base}"          (marketplace: unia.learn.example.org)
                                     "{code}-ecampus.edusite.ng"  (ITEMS)
    CAMPUS_TENANT_PLATFORM_NAME      "{name} on {platform_name}"  (marketplace)
                                     "{name} eCampus"             (ITEMS)
    CAMPUS_TENANT_MKTG_ROOT          optional "{code}"-template for the tenant's "/" and "/courses"
                                     landing (marketplace: institution profile page; control plane: portal)
    CAMPUS_TENANT_MFE_HOST_TEMPLATE  optional "{host}"-template for a per-tenant MFE host (ITEMS:
                                     "apps.{host}"); empty = the central MFE host serves every tenant

Called by the marketplace partner queue and by the control-plane integration API
(``POST /campus/api/v1/institutions/``, ITEMS). Idempotent.
"""
import json
import logging
import re
import secrets
from urllib.parse import urlparse

from django.conf import settings
from django.db import transaction

from . import events, identity, keycloak
from .models import StaffInvitation

log = logging.getLogger(__name__)

CODE_RE = re.compile(r"^[A-Z][A-Z0-9]{1,15}$")
RESERVED_CODES = {"WWW", "LMS", "CMS", "STUDIO", "APPS", "AUTH", "API", "ADMIN", "STAGING", "ITEMS", "SEMS", "EDULAGE"}


def suggest_code(name):
    words = re.findall(r"[A-Za-z0-9]+", name or "")
    code = "".join(w[0] for w in words if w[0].isalpha()).upper()
    if len(code) < 2:
        code = re.sub(r"[^A-Z0-9]", "", (name or "").upper())[:8]
    return code[:16]


def _format(template, code, name):
    return template.format(
        code=code.lower(), CODE=code, name=name,
        lms_base=settings.LMS_BASE, platform_name=settings.PLATFORM_NAME,
    )


def tenant_host(code, name=""):
    return _format(settings.CAMPUS_TENANT_HOST_TEMPLATE, code, name)


def tenant_platform_name(code, name):
    return _format(settings.CAMPUS_TENANT_PLATFORM_NAME, code, name)


def tenant_mfe_host(host):
    template = settings.CAMPUS_TENANT_MFE_HOST_TEMPLATE
    return template.format(host=host) if template else ""


def _central_mfe_host():
    return urlparse(settings.LEARNER_HOME_MICROFRONTEND_URL or "").netloc


_MFE_URL_SETTINGS = (
    "MFE_CONFIG", "FRONTEND_SITE_CONFIG", "AUTHN_MICROFRONTEND_URL", "AUTHN_MICROFRONTEND_DOMAIN",
    "ACCOUNT_MICROFRONTEND_URL", "COURSE_AUTHORING_MICROFRONTEND_URL", "DISCUSSIONS_MICROFRONTEND_URL",
    "WRITABLE_GRADEBOOK_URL", "LEARNER_HOME_MICROFRONTEND_URL", "INSTRUCTOR_MICROFRONTEND_URL",
    "LEARNING_MICROFRONTEND_URL", "ORA_GRADING_MICROFRONTEND_URL", "PROFILE_MICROFRONTEND_URL",
    "COMMUNICATIONS_MICROFRONTEND_URL", "ADMIN_CONSOLE_MICROFRONTEND_URL", "CATALOG_MICROFRONTEND_URL",
)


def mfe_configs(host):
    """
    Settings that move the tenant's micro-frontends onto ``tenant_mfe_host(host)``: every central
    MFE/LMS URL setting is re-pointed at the tenant hosts and the session cookie is scoped to the
    tenant subtree (``.<host>``) so the MFE host can carry the LMS session — never the shared parent.
    """
    mfe_host = tenant_mfe_host(host)
    if not mfe_host:
        return {}
    central_mfe, central_lms = _central_mfe_host(), settings.LMS_BASE

    def repoint(value):
        text = json.dumps(value)
        if central_mfe:
            text = text.replace(central_mfe, mfe_host)
        return json.loads(text.replace(central_lms, host))

    configs = {
        name: repoint(getattr(settings, name))
        for name in _MFE_URL_SETTINGS
        if getattr(settings, name, None) is not None
    }
    configs.update({
        "SESSION_COOKIE_DOMAIN": f".{host}",
        "SHARED_COOKIE_DOMAIN": f".{host}",
        "CSRF_COOKIE_DOMAIN": None,
        "CORS_ORIGIN_WHITELIST": sorted({*settings.CORS_ORIGIN_WHITELIST, f"https://{host}", f"https://{mfe_host}"}),
        "CSRF_TRUSTED_ORIGINS": sorted({*settings.CSRF_TRUSTED_ORIGINS, f"https://{host}", f"https://{mfe_host}"}),
        "LOGIN_REDIRECT_WHITELIST": sorted({*getattr(settings, "LOGIN_REDIRECT_WHITELIST", []), host, mfe_host}),
    })
    return configs


def code_available(code):
    from organizations.models import Organization  # pylint: disable=import-outside-toplevel

    return bool(CODE_RE.match(code)) and code not in RESERVED_CODES and not Organization.objects.filter(short_name=code).exists()


def lms_configs(code, name, extra=None):
    host = tenant_host(code, name)
    platform_name = tenant_platform_name(code, name)
    configs = {
        "EDNX_USE_SIGNAL": True,
        "SITE_NAME": host,
        "LMS_BASE": host,
        "LMS_ROOT_URL": f"https://{host}",
        "PLATFORM_NAME": platform_name,
        "platform_name": platform_name,
        "course_org_filter": [code],
        "CAMPUS_INSTITUTION": code,
        "CAMPUS_INSTITUTION_NAME": name,
        # Session cookies stay on the tenant host; never the shared parent domain.
        "SESSION_COOKIE_DOMAIN": None,
    }
    configs.update(mfe_configs(host))
    if "MFE_CONFIG" in configs:
        configs["MFE_CONFIG"]["SITE_NAME"] = configs["PLATFORM_NAME"]
    root_template = settings.CAMPUS_TENANT_MKTG_ROOT
    if root_template:
        landing = _format(root_template, code, name)
        configs["MKTG_URLS"] = {**settings.MKTG_URLS, "ROOT": landing, "COURSES": landing}
    configs.update(extra or {})
    return configs


def provision_institution(code, name, actor=None, admin_email=None, meta=None, extra_lms_configs=None):
    """
    Create/refresh the organisation, tenant config and host route for ``code``; optionally create
    the first institution-admin invitation for ``admin_email``. Returns (TenantConfig, invitation).
    """
    from eox_tenant.models import Route, TenantConfig  # pylint: disable=import-outside-toplevel
    from organizations.models import Organization  # pylint: disable=import-outside-toplevel

    host = tenant_host(code, name)
    with transaction.atomic():
        # eox-tenant's save signal calls Organization.get_or_create(name=code, short_name=code), so the
        # organisation must carry the code as its name; the display name lives in the tenant config.
        tenant, _ = TenantConfig.objects.update_or_create(
            external_key=code.lower(),
            defaults={
                "lms_configs": lms_configs(code, name, extra_lms_configs),
                "studio_configs": {},
                "theming_configs": {},
                "meta": {"institution": code, "institution_name": name, **(meta or {})},
            },
        )
        Route.objects.update_or_create(domain=host, defaults={"config": tenant})
        if tenant_mfe_host(host):
            # The MFE host resolves to the same tenant so ``/api/mfe_config`` served on it is tenant-scoped.
            Route.objects.update_or_create(domain=tenant_mfe_host(host), defaults={"config": tenant})
        Organization.objects.get_or_create(short_name=code, defaults={"name": code, "description": name, "active": True})
        Organization.objects.filter(short_name=code).update(description=name, active=True)
        invitation = None
        if admin_email:
            invitation = StaffInvitation.objects.create(
                token=secrets.token_urlsafe(32), email=admin_email, institution=code,
                role="institution_admin", invited_by=actor,
            )
            identity.audit("invited", user=actor, email=admin_email, detail=f"{invitation.claim} by provisioning", actor="provisioning")
        events.emit("institution.provisioned", {"code": code, "name": name, "host": host}, institution=code)
        identity.audit("institution_provisioned", user=actor, email=admin_email or "", detail=f"{code}: {name} @ {host}", actor="provisioning")
    _ensure_sso_provider(host)
    _sync_redirect_host(host, True)
    log.info("campus: provisioned institution %s (%s) on %s", code, name, host)
    return tenant, invitation


def _ensure_sso_provider(host):
    """
    Third-party-auth provider configs are per Django Site and the site is resolved from the request
    host, so a tenant host needs its own Site plus a copy of the central LMS host's ``campus``
    provider (same client/issuer; only the site differs).
    """
    from django.contrib.sites.models import Site  # pylint: disable=import-outside-toplevel
    from common.djangoapps.third_party_auth.models import OAuth2ProviderConfig  # pylint: disable=import-outside-toplevel

    site, _ = Site.objects.get_or_create(domain=host, defaults={"name": host})
    if OAuth2ProviderConfig.objects.filter(site=site, backend_name="campus").exists():
        return
    source = (
        OAuth2ProviderConfig.objects.filter(site__domain=settings.LMS_BASE, backend_name="campus", enabled=True)
        .order_by("-change_date").first()
    )
    if source is None:
        log.warning("campus: no enabled campus provider on %s; SSO not configured for %s", settings.LMS_BASE, host)
        return
    source.pk = None
    source.id = None
    source.site = site
    source.save()


def _sync_redirect_host(host, allowed):
    """Best effort: the route is authoritative; a stale IdP redirect list is repaired on re-provision."""
    if not keycloak.configured():
        return
    try:
        keycloak.set_redirect_host(host, allowed)
    except keycloak.KeycloakError as exc:
        log.warning("campus: could not update IdP redirect URI for %s: %s", host, exc)


def deactivate_institution(code, actor=None):
    """Mark the organisation inactive and drop its host route; data and enrolments are kept."""
    from eox_tenant.models import Route, TenantConfig  # pylint: disable=import-outside-toplevel
    from organizations.models import Organization  # pylint: disable=import-outside-toplevel

    with transaction.atomic():
        Organization.objects.filter(short_name=code).update(active=False)
        for tenant in TenantConfig.objects.filter(external_key=code.lower()):
            for route in Route.objects.filter(config=tenant):
                _sync_redirect_host(route.domain, False)
            Route.objects.filter(config=tenant).delete()
        identity.audit("institution_deactivated", user=actor, detail=code, actor="provisioning")
