"""
EduLage web certificate: the institution awards and issues the credential, EduLage records and
verifies it. Rendered through Open edX's ``CertificateRenderStarted`` filter (see
``filters.EdulageCertificate``): the stock context is kept, EduLage wording and listing metadata
are added, and the page is drawn by ``templates/edulage_platform/certificate.html`` (Mako).
"""
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from django.conf import settings
from opaque_keys import InvalidKeyError
from opaque_keys.edx.keys import CourseKey

from .models import CourseListing

SITE_URL = "https://edulage.org"
VERIFY_URL = f"{SITE_URL}/verify/"

# Loaded into `CertificateHtmlViewConfiguration` (Django admin → Certificates) by the
# `edulage_certificate_config` management command; keys are read by the LMS webview.
HTML_VIEW_CONFIGURATION = {
    "default": {
        "accomplishment_class_append": "accomplishment-certificate",
        "platform_name": "EduLage",
        "company_about_url": f"{SITE_URL}/about",
        "company_privacy_url": f"{SITE_URL}/privacy",
        "company_tos_url": f"{SITE_URL}/terms",
        "company_verified_certificate_url": f"{SITE_URL}/quality-and-trust",
        "logo_src": "/static/edulage/logo.svg",
        "logo_url": SITE_URL,
        "certificate_verify_url_prefix": VERIFY_URL,
        "certificate_verify_url_suffix": "",
        "certificate_type": "Certificate",
    },
    "honor": {"certificate_type": "Certificate"},
    "verified": {"certificate_type": "Verified certificate"},
    "professional": {"certificate_type": "Professional certificate"},
    "no-id-professional": {"certificate_type": "Professional certificate"},
    "audit": {"certificate_type": "Certificate"},
}


TEMPLATE_PATH = Path(__file__).parent / "templates" / "edulage_platform" / "certificate.html"


@dataclass(frozen=True)
class MakoTemplate:
    """Duck-types ``CertificateTemplate`` for ``_render_valid_certificate``."""

    template: str


def certificate_template():
    return MakoTemplate(TEMPLATE_PATH.read_text(encoding="utf-8"))


def ensure_html_view_configuration():
    """Activate the EduLage `CertificateHtmlViewConfiguration` unless an identical one is current."""
    from lms.djangoapps.certificates.models import CertificateHtmlViewConfiguration  # pylint: disable=import-outside-toplevel

    current = CertificateHtmlViewConfiguration.current()
    wanted = json.dumps(HTML_VIEW_CONFIGURATION, indent=2, sort_keys=True)
    if current.enabled and json.loads(current.configuration or "{}") == HTML_VIEW_CONFIGURATION:
        return False
    CertificateHtmlViewConfiguration.objects.create(enabled=True, configuration=wanted)
    return True


def brand_url():
    return getattr(settings, "EDULAGE_BRAND_URL", "") or f"https://apps.{settings.LMS_BASE}/brand"


def listing_context(course_id):
    """EduLage listing metadata for the certificate, or the org-only fallback."""
    try:
        key = CourseKey.from_string(str(course_id))
    except InvalidKeyError:
        return {}
    listing = CourseListing.objects.filter(course_key=key).first()
    if listing is None:
        return {
            "institution": key.org,
            "institution_name": "",
            "institution_url": "",
            "programme_title": "",
            "programme_url": "",
            "classification_label": "Course",
            "credential": "",
            "delivery_mode": "",
        }
    return listing.as_dict()


def certificate_context(context):
    """Extra template variables: EduLage wording + listing, on top of the stock context."""
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
            "site_url": SITE_URL,
            "brand_url": brand_url(),
            "institution": institution,
            "institution_url": listing.get("institution_url", ""),
            "programme_title": listing.get("programme_title", ""),
            "programme_url": listing.get("programme_url", ""),
            "classification": listing.get("classification_label", "Course"),
            "credential": credential,
            "delivery_mode": listing.get("delivery_mode", ""),
            "awarded_by": f"Awarded and issued by {institution}",
            "recorded_by": "Recorded and verifiable through EduLage",
            "verify_note": (
                "This credential is issued by the awarding institution. EduLage holds the record "
                "and lets anyone confirm its authenticity using the credential ID below."
            ),
        }
    }
