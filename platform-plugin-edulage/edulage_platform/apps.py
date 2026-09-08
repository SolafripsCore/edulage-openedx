from django.apps import AppConfig


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
