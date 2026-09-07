ENROLLMENT_FILTER = "org.openedx.learning.course.enrollment.started.v1"
ADMISSION_STEP = "edulage_platform.filters.RequireAdmission"
OIDC_BACKEND = "edulage_platform.auth.EdulageOpenIdConnect"
ROLE_SYNC_STEP = "edulage_platform.pipeline.sync_edulage_roles"


def plugin_settings(settings):
    """Applied at the `production` settings stage of both LMS and CMS."""
    if not hasattr(settings, "EDULAGE_ENFORCE_ADMISSION"):
        settings.EDULAGE_ENFORCE_ADMISSION = True

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
    pipeline = list(settings.SOCIAL_AUTH_PIPELINE)
    if ROLE_SYNC_STEP not in pipeline:
        pipeline.insert(pipeline.index("social_core.pipeline.user.user_details") + 1, ROLE_SYNC_STEP)
        settings.SOCIAL_AUTH_PIPELINE = pipeline
    # Logging out of Open edX also ends the EduLage IdP session (provider's `logout_url` setting).
    settings.TPA_AUTOMATIC_LOGOUT_ENABLED = True
