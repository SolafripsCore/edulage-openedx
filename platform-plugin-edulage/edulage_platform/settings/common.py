from pathlib import Path

ENROLLMENT_FILTER = "org.openedx.learning.course.enrollment.started.v1"
ADMISSION_STEP = "edulage_platform.filters.RequireAdmission"
CERTIFICATE_FILTER = "org.openedx.learning.certificate.render.started.v1"
CERTIFICATE_STEP = "edulage_platform.filters.EdulageCertificate"
OIDC_BACKEND = "edulage_platform.auth.EdulageOpenIdConnect"
SUSPENDED_STEP = "edulage_platform.pipeline.refuse_suspended_identity"
LINK_STEP = "edulage_platform.pipeline.link_verified_account"
IDENTITY_SYNC_STEP = "edulage_platform.pipeline.sync_edulage_identity"
LEGACY_ROLE_SYNC_STEP = "edulage_platform.pipeline.sync_edulage_roles"
ACCOUNT_STATUS_MIDDLEWARE = "edulage_platform.middleware.AccountStatusMiddleware"
# Django templates that replace stock/theme files by path (ACE e-mail frame); searched before the theme.
TEMPLATE_OVERRIDES = str(Path(__file__).resolve().parent.parent / "templates" / "overrides")


def plugin_settings(settings):
    """Applied at the `production` settings stage of both LMS and CMS."""
    if not hasattr(settings, "EDULAGE_ENFORCE_ADMISSION"):
        settings.EDULAGE_ENFORCE_ADMISSION = True
    # Django group whose members may call the control-plane integration API.
    if not hasattr(settings, "EDULAGE_INTEGRATION_GROUP"):
        settings.EDULAGE_INTEGRATION_GROUP = "edulage_integration"
    # Staff (any EduLage role above learner) get a short LMS session; learners keep the default.
    if not hasattr(settings, "EDULAGE_STAFF_SESSION_SECONDS"):
        settings.EDULAGE_STAFF_SESSION_SECONDS = 3600
    if not hasattr(settings, "EDULAGE_BRAND_URL"):
        settings.EDULAGE_BRAND_URL = f"https://apps.{settings.LMS_BASE}/brand"
    if not hasattr(settings, "EDULAGE_EMAIL_FROM"):
        settings.EDULAGE_EMAIL_FROM = ""  # empty → DEFAULT_FROM_EMAIL at send time
    # Institution course admins set enrolment policy/price in Studio → Advanced settings → Other course settings.
    settings.FEATURES["ENABLE_OTHER_COURSE_SETTINGS"] = True
    # Paystack (test or live secret; never logged). Empty disables checkout.
    if not hasattr(settings, "EDULAGE_PAYSTACK_SECRET_KEY"):
        settings.EDULAGE_PAYSTACK_SECRET_KEY = ""
    if not hasattr(settings, "EDULAGE_PAYSTACK_PUBLIC_KEY"):
        settings.EDULAGE_PAYSTACK_PUBLIC_KEY = ""
    if not hasattr(settings, "EDULAGE_SITE_URL"):
        settings.EDULAGE_SITE_URL = "https://edulage.org"
    if not hasattr(settings, "EDULAGE_STUDIO_URL"):
        settings.EDULAGE_STUDIO_URL = f"https://{settings.CMS_BASE}" if getattr(settings, "CMS_BASE", "") else ""
    # Identity-provider admin client for the institution console (empty → invitations disabled).
    if not hasattr(settings, "EDULAGE_KC_URL"):
        settings.EDULAGE_KC_URL = ""
    if not hasattr(settings, "EDULAGE_KC_REALM"):
        settings.EDULAGE_KC_REALM = "edulage"
    if not hasattr(settings, "EDULAGE_KC_CLIENT_ID"):
        settings.EDULAGE_KC_CLIENT_ID = "edulage-lms-console"
    if not hasattr(settings, "EDULAGE_KC_CLIENT_SECRET"):
        settings.EDULAGE_KC_CLIENT_SECRET = ""
    if not hasattr(settings, "EDULAGE_BILLING_EMAIL"):
        settings.EDULAGE_BILLING_EMAIL = "billing@edulage.org"
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
    if IDENTITY_SYNC_STEP not in pipeline:
        pipeline.insert(pipeline.index("social_core.pipeline.user.user_details") + 1, IDENTITY_SYNC_STEP)
    settings.SOCIAL_AUTH_PIPELINE = pipeline
    # Logging out of Open edX also ends the EduLage IdP session (provider's `logout_url` setting).
    settings.TPA_AUTOMATIC_LOGOUT_ENABLED = True
