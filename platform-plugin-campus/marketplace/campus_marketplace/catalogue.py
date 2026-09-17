"""
Enrolment policy and price are owned by the institution's course admin and set in Studio:
Settings → Advanced settings → "Other course settings":

    {"marketplace": {"enrolment_policy": "open_paid", "price": 25000, "currency": "NGN"}}

(the legacy ``"edulage"`` key is still read for courses configured before the rename).

``enrolment_policy`` is one of ``admission`` (default), ``open_free``, ``open_paid``. On every
publish (CMS ``course_published`` signal) the values are mirrored into ``CourseListing`` — the
row the LMS enrolment filter, the public run API and the My learning cards read.
"""
import logging
from decimal import Decimal, InvalidOperation

from django.dispatch import receiver

from .models import CourseListing

log = logging.getLogger(__name__)

POLICIES = {p for p, _ in CourseListing.POLICIES}
# accepted spellings from the Studio JSON
POLICY_ALIASES = {"open-free": "open_free", "open-paid": "open_paid", "free": "open_free", "paid": "open_paid"}


SETTINGS_KEYS = ("marketplace", "edulage")


def parse_marketplace_settings(other_course_settings):
    """Return ``{"enrolment_policy", "price", "currency"}`` or ``None`` when nothing is set / it is invalid."""
    other = other_course_settings or {}
    raw = next((other[k] for k in SETTINGS_KEYS if k in other), None)
    if not isinstance(raw, dict):
        return None
    policy = str(raw.get("enrolment_policy", CourseListing.POLICY_ADMISSION)).strip().lower()
    policy = POLICY_ALIASES.get(policy, policy)
    if policy not in POLICIES:
        log.warning("campus: ignoring unknown enrolment_policy %r", policy)
        return None
    try:
        price = Decimal(str(raw.get("price", 0))).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        log.warning("campus: ignoring invalid price %r", raw.get("price"))
        return None
    if policy == CourseListing.POLICY_OPEN_PAID and price <= 0:
        log.warning("campus: open_paid run without a positive price; treating as admission")
        return None
    if policy != CourseListing.POLICY_OPEN_PAID:
        price = Decimal("0.00")
    currency = str(raw.get("currency", "NGN")).upper()[:3] or "NGN"
    return {"enrolment_policy": policy, "price": price, "currency": currency}


def sync_listing_from_course(course_key):
    """Mirror the Studio-set policy/price into CourseListing (creating a minimal row if needed)."""
    from xmodule.modulestore.django import modulestore  # pylint: disable=import-outside-toplevel

    course = modulestore().get_course(course_key)
    if course is None:
        return None
    values = parse_marketplace_settings(course.other_course_settings)
    if values is None:
        return None
    listing = CourseListing.objects.filter(course_key=course_key).first()
    if listing is None:
        listing = CourseListing(course_key=course_key, institution=course_key.org, institution_name=course.display_org_with_default)
    listing.enrolment_policy = values["enrolment_policy"]
    listing.price = values["price"]
    listing.currency = values["currency"]
    listing.save(update_fields=None if listing.pk is None else ["enrolment_policy", "price", "currency", "modified"])
    log.info("campus: %s enrolment_policy=%s price=%s %s", course_key, listing.enrolment_policy, listing.price, listing.currency)
    return listing


def connect_cms_signals():
    from xmodule.modulestore.django import SignalHandler  # pylint: disable=import-outside-toplevel

    @receiver(SignalHandler.course_published, dispatch_uid="campus_listing_sync")
    def _on_publish(sender, course_key, **kwargs):  # pylint: disable=unused-argument
        try:
            sync_listing_from_course(course_key)
        except Exception:  # pylint: disable=broad-except
            log.exception("campus: listing sync failed for %s", course_key)
