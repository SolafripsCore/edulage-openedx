"""Seed the multi-tenancy/SSO spike in the LMS.

Run:  tutor local run -e EDULAGE_OIDC_SECRET=... lms ./manage.py lms shell < scripts/spike/seed_lms.py

Creates two institutions (Open edX organisations + eox-tenant tenants/routes), the
EduLage OIDC provider (Keycloak stand-in) and a pre-existing "legacy" LMS account used
to prove account linking. Idempotent.
"""
import os
import secrets

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.sites.models import Site
from eox_tenant.models import Route, TenantConfig
from oauth2_provider.models import Application
from openedx.core.djangoapps.oauth_dispatch.models import ApplicationAccess
from organizations.models import Organization
from social_django.models import UserSocialAuth
from common.djangoapps.student.models import UserProfile
from common.djangoapps.third_party_auth.models import OAuth2ProviderConfig
from edulage_platform.models import CourseListing
from opaque_keys.edx.keys import CourseKey

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

# Platform host: learners arrive here from edulage.org, so My learning must list enrolments across
# every institution. Without an explicit filter Open edX blacklists every org that is claimed by
# some other tenant, which would empty the dashboard. Institution-scoped UIs stay on tenant hosts.
platform, _ = TenantConfig.objects.update_or_create(
    external_key="platform",
    defaults={
        "lms_configs": {"EDNX_USE_SIGNAL": True, "course_org_filter": sorted(INSTITUTIONS)},
        "studio_configs": {},
        "theming_configs": {},
        "meta": {"edulage_institution": None},
    },
)
Route.objects.update_or_create(domain=LMS_HOST, defaults={"config": platform})
print(f"platform host {LMS_HOST} org_filter={platform.get_organizations()}")

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


def legacy_account(username, email, name):
    u, was_created = User.objects.get_or_create(username=username, defaults={"email": email, "is_active": True})
    if was_created:
        u.set_password(secrets.token_urlsafe(32))
        u.save()
    UserProfile.objects.get_or_create(user=u, defaults={"name": name})
    return u


# A realm re-import in the stand-in IdP issues new `sub`s; drop links to the dead identities so
# the linking proof can start from a clean state (never done against production identities).
if os.environ.get("EDULAGE_RESET_LINKS") == "1":
    n, _ = UserSocialAuth.objects.filter(provider="edulage").delete()
    print("reset edulage identity links:", n)

# Pre-existing account whose email matches IdP user dupe.learner but which is already bound to a
# different EduLage identity -> the link must be refused. (auth_user.email is unique with a
# case-insensitive collation on this deployment, so two accounts with the same email cannot exist;
# the ambiguity guard in pipeline.link_verified_account is defence in depth.)
taken = legacy_account("dupe_taken", "dupe.learner@example.org", "Dupe Taken")
UserSocialAuth.objects.get_or_create(provider="edulage", uid="00000000-dead-dead-dead-000000000000", defaults={"user": taken})

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
    group, _ = Group.objects.get_or_create(name=settings.EDULAGE_INTEGRATION_GROUP)
    svc.groups.add(group)
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

# EduLage catalogue metadata for the pilot runs (normally pushed by the control plane via
# PUT /edulage/api/v1/listings/); drives institution / classification / programme on My learning cards.
LISTINGS = {
    "course-v1:UNIA+CS101+2026": {
        "institution": "UNIA", "institution_name": "University A", "institution_url": "https://edulage.org/institutions/unia",
        "programme_title": "BSc Computer Science", "programme_url": "https://edulage.org/programmes/unia-bsc-computer-science",
        "classification": "degree", "credential": "BSc", "delivery_mode": "Fully online",
    },
    "course-v1:UNIB+MGT101+2026": {
        "institution": "UNIB", "institution_name": "University B", "institution_url": "https://edulage.org/institutions/unib",
        "programme_title": "Professional Certificate in Management", "programme_url": "https://edulage.org/programmes/unib-management",
        "classification": "professional", "credential": "Professional Certificate", "delivery_mode": "Online + OEC exams",
    },
}
for course_id, fields in LISTINGS.items():
    CourseListing.objects.update_or_create(course_key=CourseKey.from_string(course_id), defaults=fields)
print("listings", CourseListing.objects.count())
