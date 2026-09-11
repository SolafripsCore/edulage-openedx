from importlib import import_module

from django.apps import AppConfig
from django.conf import settings


class EdulagePlatformConfig(AppConfig):
    name = "edulage_platform"
    verbose_name = "EduLage Platform Integration"
    default_auto_field = "django.db.models.BigAutoField"

    plugin_app = {
        "url_config": {
            "lms.djangoapp": {
                "namespace": "edulage",
                "regex": r"^edulage/",
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
            import_module("edulage_platform.signals")
        elif settings.SERVICE_VARIANT == "cms":
            import_module("edulage_platform.catalogue").connect_cms_signals()
