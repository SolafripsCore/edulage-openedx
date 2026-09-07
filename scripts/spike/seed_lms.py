"""Seed the multi-tenancy/SSO spike in the LMS.

Run:  tutor local run -e EDULAGE_OIDC_SECRET=... lms ./manage.py lms shell < scripts/spike/seed_lms.py

Creates two institutions (Open edX organisations + eox-tenant tenants/routes), the
EduLage OIDC provider (Keycloak stand-in) and a pre-existing "legacy" LMS account used
to prove account linking. Idempotent.
"""
import os
import secrets

from django.contrib.auth import get_user_model
from django.contrib.sites.models import Site
from eox_tenant.models import Route, TenantConfig
from oauth2_provider.models import Application
from openedx.core.djangoapps.oauth_dispatch.models import ApplicationAccess
from organizations.models import Organization
from common.djangoapps.student.models import UserProfile
from common.djangoapps.third_party_auth.models import OAuth2ProviderConfig

INSTITUTIONS = {
    "UNIA": {"name": "University A (pilot)", "host": "unia.learn.edulage.org"},
    "UNIB": {"name": "University B (pilot)", "host": "unib.learn.edulage.org"},
}
AUTH_HOST = os.environ.get("EDULAGE_AUTH_HOST", "auth.edulage.org")
LMS_HOST = os.environ.get("LMS_HOST", "learn.edulage.org")
User = get_user_model()

for short_name, inst in INSTITUTIONS.items():
    # eox-tenant syncs `course_org_filter` -> TenantOrganization + Organization on save and
    # requires Organization.name == short_name; the display name lives in PLATFORM_NAME.
    tenant, _ = TenantConfig.objects.update_or_create(
        external_key=short_name.lower(),
        defaults={
            "lms_configs": {
                "EDNX_USE_SIGNAL": True,
                "SITE_NAME": inst["host"],
                "LMS_BASE": inst["host"],
                "LMS_ROOT_URL": f"https://{inst['host']}",
                "PLATFORM_NAME": f"{inst['name']} on EduLage",
                "platform_name": f"{inst['name']} on EduLage",
                "course_org_filter": [short_name],
                "EDULAGE_INSTITUTION": short_name,
            },
            "studio_configs": {},
            "theming_configs": {},
            "meta": {"edulage_institution": short_name},
        },
    )
    Route.objects.update_or_create(domain=inst["host"], defaults={"config": tenant})
    org = Organization.objects.get(short_name=short_name)
    print(f"tenant {short_name}: https://{inst['host']} org_filter={tenant.get_organizations()} org_id={org.id}")

site = Site.objects.get(domain=LMS_HOST)
secret = os.environ.get("EDULAGE_OIDC_SECRET", "")
current = (
    OAuth2ProviderConfig.objects.filter(site=site, backend_name="edulage").order_by("-change_date").first()
    or OAuth2ProviderConfig()
)
# ConfigurationModel: rows are append-only; saving a new row makes it the current version.
provider = current if current.id and (not secret or current.secret == secret) else OAuth2ProviderConfig(
    site=site,
    backend_name="edulage",
    enabled=True,
    name="EduLage",
    slug="edulage",
    icon_class="fa-graduation-cap",
    key="openedx",
    secret=secret,
    skip_hinted_login_dialog=True,
    skip_registration_form=True,
    skip_email_verification=True,
    send_welcome_email=False,
    sync_learner_profile_data=True,
    visible=True,
    other_settings=(
        '{"OIDC_ENDPOINT": "https://%s/realms/edulage", '
        '"logout_url": "https://%s/realms/edulage/protocol/openid-connect/logout'
        '?client_id=openedx&post_logout_redirect_uri=https://edulage.org/"}'
    )
    % (AUTH_HOST, AUTH_HOST),
)
if not provider.id:
    provider.save()
print("provider", provider.provider_id, "secret set:", bool(provider.secret))

# Pre-existing LMS account for the account-linking proof (same email as the IdP user).
legacy, created = User.objects.get_or_create(
    username="ada_legacy", defaults={"email": "ada.learner@example.org", "is_active": True}
)
if created:
    # Open edX treats an unusable password ("!" prefix) as a disabled account.
    legacy.set_password(secrets.token_urlsafe(32))
    legacy.save()
UserProfile.objects.get_or_create(user=legacy, defaults={"name": "Ada Learner (legacy)"})
print("legacy user", legacy.username, legacy.email)

# Service identity for the EduLage control plane: OAuth2 client-credentials -> JWT.
# eox-tenant only issues tokens on hosts listed in redirect_uris, so the client is bound to
# the platform host and cannot be used from an institution's tenant domain.
service_secret = os.environ.get("EDULAGE_SERVICE_CLIENT_SECRET", "")
if service_secret:
    svc, created = User.objects.get_or_create(
        username="edulage-integration",
        defaults={"email": "integration@edulage.org", "is_active": True, "is_staff": True},
    )
    if created:
        svc.set_password(secrets.token_urlsafe(32))
        svc.save()
    UserProfile.objects.get_or_create(user=svc, defaults={"name": "EduLage integration"})
    app, _ = Application.objects.update_or_create(
        name="edulage-control-plane",
        defaults={
            "user": svc,
            "client_id": "edulage-control-plane",
            "client_secret": service_secret,
            "client_type": Application.CLIENT_CONFIDENTIAL,
            "authorization_grant_type": Application.GRANT_CLIENT_CREDENTIALS,
            "skip_authorization": True,
            "redirect_uris": f"https://{LMS_HOST}/",
        },
    )
    ApplicationAccess.objects.update_or_create(application=app, defaults={"scopes": ["user_id"]})
    print("service client", app.client_id, "user", svc.username)
