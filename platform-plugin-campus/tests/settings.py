"""Minimal settings for makemigrations / unit tests outside Open edX."""
SECRET_KEY = "test"
INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "campus_platform",
    "campus_marketplace",
]
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
USE_TZ = True
SERVICE_VARIANT = "test"
LMS_BASE = "learn.example.org"
LMS_ROOT_URL = "https://learn.example.org"
PLATFORM_NAME = "Example Campus"
MKTG_URLS = {}
CAMPUS_TENANT_HOST_TEMPLATE = "{code}.{lms_base}"
CAMPUS_TENANT_PLATFORM_NAME = "{name} on {platform_name}"
CAMPUS_TENANT_MKTG_ROOT = ""
CAMPUS_TENANT_MFE_HOST_TEMPLATE = ""
CAMPUS_ENROLMENT_POLICY_PROVIDER = ""
CAMPUS_COURSE_METADATA_PROVIDER = ""
CAMPUS_WEBHOOK_URL = "https://items.example.org/hooks/campus"
CAMPUS_WEBHOOK_SECRET = "test-secret"
