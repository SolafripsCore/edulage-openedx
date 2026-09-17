from importlib import import_module

from django.apps import AppConfig
from django.conf import settings


class CampusMarketplaceConfig(AppConfig):
    """Marketplace product layer (public catalogue, self-enrolment, Paystack checkout, partner onboarding)."""

    name = "campus_marketplace"
    verbose_name = "Campus Marketplace"
    default_auto_field = "django.db.models.BigAutoField"

    plugin_app = {
        "url_config": {
            "lms.djangoapp": {
                "namespace": "campus_marketplace",
                "regex": r"^campus/",
                "relative_path": "urls",
            },
        },
        "settings_config": {
            "lms.djangoapp": {"production": {"relative_path": "settings.common"}},
            "cms.djangoapp": {"production": {"relative_path": "settings.common"}},
        },
    }

    def ready(self):
        if settings.SERVICE_VARIANT == "cms":
            import_module("campus_marketplace.catalogue").connect_cms_signals()
