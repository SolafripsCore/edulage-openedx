"""
Campus web certificate: the institution awards and issues the credential, the platform records and
verifies it. Rendered through Open edX's ``CertificateRenderStarted`` filter (see
``filters.CampusCertificate``): the stock context is kept, platform wording and listing metadata
are added, and the page is drawn by ``templates/campus_platform/certificate.html`` (Mako).
"""
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from django.conf import settings

from . import hooks



def site_url():
    return settings.CAMPUS_SITE_URL.rstrip("/")


def verify_url_prefix():
    return settings.CAMPUS_VERIFY_URL.rstrip("/") + "/"

# Loaded into `CertificateHtmlViewConfiguration` (Django admin → Certificates) by the
# `campus_certificate_config` management command; keys are read by the LMS webview.
def html_view_configuration():
    return {
        "default": {
            "accomplishment_class_append": "accomplishment-certificate",
            "platform_name": settings.PLATFORM_NAME,
            "company_about_url": f"{site_url()}/about",
            "company_privacy_url": f"{site_url()}/privacy",
            "company_tos_url": f"{site_url()}/terms",
            "company_verified_certificate_url": f"{site_url()}/quality-and-trust",
            "logo_src": "/static/campus/logo.svg",
            "logo_url": site_url(),
            "certificate_verify_url_prefix": verify_url_prefix(),
            "certificate_verify_url_suffix": "",
            "certificate_type": "Certificate",
        },
        "honor": {"certificate_type": "Certificate"},
        "verified": {"certificate_type": "Verified certificate"},
        "professional": {"certificate_type": "Professional certificate"},
        "no-id-professional": {"certificate_type": "Professional certificate"},
        "audit": {"certificate_type": "Certificate"},
    }



TEMPLATE_PATH = Path(__file__).parent / "templates" / "campus_platform" / "certificate.html"


@dataclass(frozen=True)
class MakoTemplate:
    """Duck-types ``CertificateTemplate`` for ``_render_valid_certificate``."""

    template: str


def certificate_template():
    return MakoTemplate(TEMPLATE_PATH.read_text(encoding="utf-8"))


def ensure_html_view_configuration():
    """Activate the campus `CertificateHtmlViewConfiguration` unless an identical one is current."""
    from lms.djangoapps.certificates.models import CertificateHtmlViewConfiguration  # pylint: disable=import-outside-toplevel

    current = CertificateHtmlViewConfiguration.current()
    wanted = json.dumps(html_view_configuration(), indent=2, sort_keys=True)
    if current.enabled and json.loads(current.configuration or "{}") == html_view_configuration():
        return False
    CertificateHtmlViewConfiguration.objects.create(enabled=True, configuration=wanted)
    return True


def brand_url():
    return settings.CAMPUS_BRAND_URL or f"https://apps.{settings.LMS_BASE}/brand"


def listing_context(course_id):
    """Course metadata for the certificate (product layer or org-only fallback)."""
    return hooks.course_metadata(course_id)


def certificate_context(context):
    """Extra template variables: platform wording + listing, on top of the stock context."""
    listing = listing_context(context.get("course_id", ""))
    institution = (
        listing.get("institution_name")
        or context.get("organization_long_name")
        or context.get("organization_short_name")
        or listing.get("institution", "")
    )
    credential = listing.get("credential") or context.get("certificate_type") or "Certificate"
    return {
        "el": {
            "year": date.today().year,
            "site_url": site_url(),
            "site_host": site_url().split("//", 1)[-1],
            "platform_name": settings.PLATFORM_NAME,
            "brand_url": brand_url(),
            "institution": institution,
            "institution_url": listing.get("institution_url", ""),
            "programme_title": listing.get("programme_title", ""),
            "programme_url": listing.get("programme_url", ""),
            "classification": listing.get("classification_label", "Course"),
            "credential": credential,
            "delivery_mode": listing.get("delivery_mode", ""),
            "awarded_by": f"Awarded and issued by {institution}",
            "recorded_by": f"Recorded and verifiable through {settings.PLATFORM_NAME}",
            "verify_note": (
                f"This credential is issued by the awarding institution. {settings.PLATFORM_NAME} holds the record "
                "and lets anyone confirm its authenticity using the credential ID below."
            ),
        }
    }
