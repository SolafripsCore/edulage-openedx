from importlib import import_module

from django.apps import AppConfig
from django.conf import settings


class CampusPlatformConfig(AppConfig):
    name = "campus_platform"
    verbose_name = "Campus Platform Integration"
    default_auto_field = "django.db.models.BigAutoField"

    plugin_app = {
        "url_config": {
            "lms.djangoapp": {
                "namespace": "campus",
                "regex": r"^campus/",
                "relative_path": "urls",
            },
        },
        "settings_config": {
            "lms.djangoapp": {
                "production": {"relative_path": "settings.common"},
            },
            "cms.djangoapp": {
                "production": {"relative_path": "settings.common"},
            },
        },
    }

    def ready(self):
        if settings.SERVICE_VARIANT == "lms":
            import_module("campus_platform.signals")
