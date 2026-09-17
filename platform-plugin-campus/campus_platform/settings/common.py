from pathlib import Path

ENROLLMENT_FILTER = "org.openedx.learning.course.enrollment.started.v1"
ADMISSION_STEP = "campus_platform.filters.RequireAdmission"
CERTIFICATE_FILTER = "org.openedx.learning.certificate.render.started.v1"
CERTIFICATE_STEP = "campus_platform.filters.CampusCertificate"
OIDC_BACKEND = "campus_platform.auth.CampusOpenIdConnect"
SUSPENDED_STEP = "campus_platform.pipeline.refuse_suspended_identity"
LINK_STEP = "campus_platform.pipeline.link_verified_account"
IDENTITY_SYNC_STEP = "campus_platform.pipeline.sync_campus_identity"
JIT_ACCOUNT_STEP = "campus_platform.pipeline.create_provisioned_account"
LEGACY_ROLE_SYNC_STEP = "campus_platform.pipeline.sync_campus_roles"
ACCOUNT_STATUS_MIDDLEWARE = "campus_platform.middleware.AccountStatusMiddleware"
# Django templates that replace stock/theme files by path (ACE e-mail frame); searched before the theme.
TEMPLATE_OVERRIDES = str(Path(__file__).resolve().parent.parent / "templates" / "overrides")


def plugin_settings(settings):
    """Applied at the `production` settings stage of both LMS and CMS."""
    if not hasattr(settings, "CAMPUS_ENFORCE_ADMISSION"):
        settings.CAMPUS_ENFORCE_ADMISSION = True
    # Django group whose members may call the control-plane integration API.
    if not hasattr(settings, "CAMPUS_INTEGRATION_GROUP"):
        settings.CAMPUS_INTEGRATION_GROUP = "campus_integration"
    # Staff (any role above learner) get a short LMS session; learners keep the default.
    if not hasattr(settings, "CAMPUS_STAFF_SESSION_SECONDS"):
        settings.CAMPUS_STAFF_SESSION_SECONDS = 3600
    if not hasattr(settings, "CONTACT_EMAIL"):
        settings.CONTACT_EMAIL = settings.DEFAULT_FROM_EMAIL
    if not hasattr(settings, "CAMPUS_BRAND_URL"):
        settings.CAMPUS_BRAND_URL = f"https://apps.{settings.LMS_BASE}/brand"
    if not hasattr(settings, "CAMPUS_EMAIL_FROM"):
        settings.CAMPUS_EMAIL_FROM = ""  # empty → DEFAULT_FROM_EMAIL at send time
    # Public site of the product running this deployment (control-plane portal); used in e-mails,
    # status pages and certificates. Credential verification page prefix for certificates.
    if not hasattr(settings, "CAMPUS_SITE_URL"):
        settings.CAMPUS_SITE_URL = settings.LMS_ROOT_URL
    if not hasattr(settings, "CAMPUS_VERIFY_URL"):
        settings.CAMPUS_VERIFY_URL = f"{settings.CAMPUS_SITE_URL.rstrip('/')}/verify"
    # Tenant provisioning conventions (see ``provisioning.py``).
    if not hasattr(settings, "CAMPUS_TENANT_HOST_TEMPLATE"):
        settings.CAMPUS_TENANT_HOST_TEMPLATE = "{code}.{lms_base}"
    if not hasattr(settings, "CAMPUS_TENANT_PLATFORM_NAME"):
        settings.CAMPUS_TENANT_PLATFORM_NAME = "{name} on {platform_name}"
    if not hasattr(settings, "CAMPUS_TENANT_MKTG_ROOT"):
        settings.CAMPUS_TENANT_MKTG_ROOT = ""
    if not hasattr(settings, "CAMPUS_TENANT_MFE_HOST_TEMPLATE"):
        settings.CAMPUS_TENANT_MFE_HOST_TEMPLATE = ""
    # Product-layer hooks (dotted paths; empty = core defaults, i.e. admission required everywhere).
    if not hasattr(settings, "CAMPUS_ENROLMENT_POLICY_PROVIDER"):
        settings.CAMPUS_ENROLMENT_POLICY_PROVIDER = ""
    if not hasattr(settings, "CAMPUS_COURSE_METADATA_PROVIDER"):
        settings.CAMPUS_COURSE_METADATA_PROVIDER = ""
    if not hasattr(settings, "CAMPUS_STUDIO_URL"):
        settings.CAMPUS_STUDIO_URL = f"https://{settings.CMS_BASE}" if hasattr(settings, "CMS_BASE") else ""
    # Control-plane webhook (empty URL disables delivery; events are still recorded for pull/replay).
    if not hasattr(settings, "CAMPUS_WEBHOOK_URL"):
        settings.CAMPUS_WEBHOOK_URL = ""
    if not hasattr(settings, "CAMPUS_WEBHOOK_SECRET"):
        settings.CAMPUS_WEBHOOK_SECRET = ""
    # Identity-provider admin client for the institution console (empty → invitations disabled).
    if not hasattr(settings, "CAMPUS_KC_URL"):
        settings.CAMPUS_KC_URL = ""
    if not hasattr(settings, "CAMPUS_KC_REALM"):
        settings.CAMPUS_KC_REALM = "campus"
    if not hasattr(settings, "CAMPUS_KC_CLIENT_ID"):
        settings.CAMPUS_KC_CLIENT_ID = "campus-lms-console"
    if not hasattr(settings, "CAMPUS_KC_CLIENT_SECRET"):
        settings.CAMPUS_KC_CLIENT_SECRET = ""
    # The learner-facing OIDC client whose redirect URIs are extended per tenant host on provisioning.
    if not hasattr(settings, "CAMPUS_KC_OIDC_CLIENT_ID"):
        settings.CAMPUS_KC_OIDC_CLIENT_ID = "openedx"
    # Create LMS accounts directly from verified IdP claims (control-plane-originated accounts) instead
    # of via the registration form; lets a deployment keep ALLOW_PUBLIC_ACCOUNT_CREATION off.
    if not hasattr(settings, "CAMPUS_JIT_ACCOUNTS"):
        settings.CAMPUS_JIT_ACCOUNTS = False
    for engine in settings.TEMPLATES:
        if engine["BACKEND"] == "django.template.backends.django.DjangoTemplates":
            dirs = list(engine.get("DIRS", []))
            if TEMPLATE_OVERRIDES not in dirs:
                engine["DIRS"] = [TEMPLATE_OVERRIDES] + dirs
    middleware = list(settings.MIDDLEWARE)
    if ACCOUNT_STATUS_MIDDLEWARE not in middleware:
        anchor = next(i for i, m in enumerate(middleware) if m.endswith(("UserStandingMiddleware", "AuthenticationMiddleware")))
        middleware.insert(anchor + 1, ACCOUNT_STATUS_MIDDLEWARE)
        settings.MIDDLEWARE = middleware

    if not hasattr(settings, "OPEN_EDX_FILTERS_CONFIG"):
        settings.OPEN_EDX_FILTERS_CONFIG = {}
    entry = settings.OPEN_EDX_FILTERS_CONFIG.setdefault(
        ENROLLMENT_FILTER, {"fail_silently": False, "pipeline": []}
    )
    if ADMISSION_STEP not in entry["pipeline"]:
        entry["pipeline"].append(ADMISSION_STEP)
    cert_entry = settings.OPEN_EDX_FILTERS_CONFIG.setdefault(
        CERTIFICATE_FILTER, {"fail_silently": False, "pipeline": []}
    )
    if CERTIFICATE_STEP not in cert_entry["pipeline"]:
        cert_entry["pipeline"].append(CERTIFICATE_STEP)

    # Studio authenticates against the LMS via OAuth2; the IdP backend lives in the LMS only.
    if settings.SERVICE_VARIANT != "lms" or not settings.FEATURES.get("ENABLE_THIRD_PARTY_AUTH"):
        return

    backends = list(settings.AUTHENTICATION_BACKENDS)
    if OIDC_BACKEND not in backends:
        settings.AUTHENTICATION_BACKENDS = [OIDC_BACKEND] + backends
    pipeline = [s for s in settings.SOCIAL_AUTH_PIPELINE if s != LEGACY_ROLE_SYNC_STEP]
    if SUSPENDED_STEP not in pipeline:
        pipeline.insert(pipeline.index("social_core.pipeline.social_auth.social_uid") + 1, SUSPENDED_STEP)
    if LINK_STEP not in pipeline:
        pipeline.insert(pipeline.index("social_core.pipeline.social_auth.social_user") + 1, LINK_STEP)
    if JIT_ACCOUNT_STEP not in pipeline:
        pipeline.insert(pipeline.index(LINK_STEP) + 1, JIT_ACCOUNT_STEP)
    if IDENTITY_SYNC_STEP not in pipeline:
        pipeline.insert(pipeline.index("social_core.pipeline.user.user_details") + 1, IDENTITY_SYNC_STEP)
    settings.SOCIAL_AUTH_PIPELINE = pipeline
    # Logging out of Open edX also ends the IdP session (provider's `logout_url` setting).
    settings.TPA_AUTOMATIC_LOGOUT_ENABLED = True
