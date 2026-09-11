ENROLLMENT_FILTER = "org.openedx.learning.course.enrollment.started.v1"
ADMISSION_STEP = "edulage_platform.filters.RequireAdmission"
OIDC_BACKEND = "edulage_platform.auth.EdulageOpenIdConnect"
LINK_STEP = "edulage_platform.pipeline.link_verified_account"
IDENTITY_SYNC_STEP = "edulage_platform.pipeline.sync_edulage_identity"
LEGACY_ROLE_SYNC_STEP = "edulage_platform.pipeline.sync_edulage_roles"
ACCOUNT_STATUS_MIDDLEWARE = "edulage_platform.middleware.AccountStatusMiddleware"


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

    # Studio authenticates against the LMS via OAuth2; the IdP backend lives in the LMS only.
    if settings.SERVICE_VARIANT != "lms" or not settings.FEATURES.get("ENABLE_THIRD_PARTY_AUTH"):
        return

    backends = list(settings.AUTHENTICATION_BACKENDS)
    if OIDC_BACKEND not in backends:
        settings.AUTHENTICATION_BACKENDS = [OIDC_BACKEND] + backends
    pipeline = [s for s in settings.SOCIAL_AUTH_PIPELINE if s != LEGACY_ROLE_SYNC_STEP]
    if LINK_STEP not in pipeline:
        pipeline.insert(pipeline.index("social_core.pipeline.social_auth.social_user") + 1, LINK_STEP)
    if IDENTITY_SYNC_STEP not in pipeline:
        pipeline.insert(pipeline.index("social_core.pipeline.user.user_details") + 1, IDENTITY_SYNC_STEP)
    settings.SOCIAL_AUTH_PIPELINE = pipeline
    # Logging out of Open edX also ends the EduLage IdP session (provider's `logout_url` setting).
    settings.TPA_AUTOMATIC_LOGOUT_ENABLED = True
