"""
Open enrolment: free runs enrol directly; paid runs go through Paystack.

Browser entry points (linked from marketplace programme pages and the LMS):

* ``GET /campus/enrol/<course_id>/``   — free run: enrol and continue to the course
                                           (paid run: redirects to checkout; admission run: status page).
* ``GET /campus/pay/<course_id>/``     — paid run: create a Payment, initialise a Paystack
                                           transaction and redirect to Paystack's checkout.
* ``GET /campus/pay/callback/``        — Paystack sends the browser back here. The reference is
                                           verified server-side (``/transaction/verify``); the
                                           browser is never trusted.
* ``POST /campus/pay/webhook/``        — Paystack webhook (``charge.success``), accepted only with
                                           a valid ``x-paystack-signature`` (HMAC-SHA512 of the raw body).

Settlement is idempotent: ``settle()`` moves a Payment to ``success`` once, enrols once
(``Payment.enrolled``) and sends one receipt (``SentEmail``), whichever of callback or webhook
arrives first. Amount and currency returned by Paystack must match what we charged.
"""
import hashlib
import hmac
import json
import logging
import uuid
from decimal import Decimal
from urllib.parse import urlencode

import requests
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import Http404, HttpResponse, HttpResponseBadRequest, HttpResponseRedirect
from django.shortcuts import render
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from opaque_keys import InvalidKeyError
from opaque_keys.edx.keys import CourseKey

from campus_platform.status import page_url

from . import emails
from .models import CourseListing, Payment

log = logging.getLogger(__name__)

PAYSTACK_API = "https://api.paystack.co"
TIMEOUT = 20


class PaystackError(Exception):
    pass


def _secret():
    key = settings.MARKETPLACE_PAYSTACK_SECRET_KEY
    if not key:
        raise PaystackError("Paystack is not configured")
    return key


def _api(method, path, **kwargs):
    resp = requests.request(
        method, f"{PAYSTACK_API}{path}", headers={"Authorization": f"Bearer {_secret()}"}, timeout=TIMEOUT, **kwargs
    )
    try:
        body = resp.json()
    except ValueError as exc:
        raise PaystackError(f"Paystack returned non-JSON ({resp.status_code})") from exc
    if not resp.ok or not body.get("status"):
        raise PaystackError(body.get("message") or f"Paystack HTTP {resp.status_code}")
    return body["data"]


def _course_key(course_id):
    try:
        return CourseKey.from_string(course_id)
    except InvalidKeyError as exc:
        raise Http404 from exc


def _listing(course_key):
    listing = CourseListing.objects.filter(course_key=course_key).first()
    if listing is None or not listing.is_open:
        return None
    return listing


def _course_home(course_key):
    return f"{settings.LEARNING_MICROFRONTEND_URL}/course/{course_key}/home"


def _enrol(user, course_key):
    from common.djangoapps.student.models import CourseEnrollment  # pylint: disable=import-outside-toplevel

    CourseEnrollment.enroll(user, course_key, mode="honor", check_access=False)


def _is_enrolled(user, course_key):
    from common.djangoapps.student.models import CourseEnrollment  # pylint: disable=import-outside-toplevel

    return CourseEnrollment.is_enrolled(user, course_key)


# --------------------------------------------------------------------------------------- views


@never_cache
@login_required
def enrol_view(request, course_id):
    course_key = _course_key(course_id)
    if _is_enrolled(request.user, course_key):
        return HttpResponseRedirect(_course_home(course_key))
    listing = _listing(course_key)
    if listing is None:
        return HttpResponseRedirect(page_url("pending"))
    if listing.is_paid:
        return HttpResponseRedirect(f"/campus/pay/{course_key}/")
    _enrol(request.user, course_key)
    log.info("campus: open-free enrolment %s → %s", request.user.username, course_key)
    return HttpResponseRedirect(_course_home(course_key))


@never_cache
@login_required
def pay_view(request, course_id):
    course_key = _course_key(course_id)
    if _is_enrolled(request.user, course_key):
        return HttpResponseRedirect(_course_home(course_key))
    listing = _listing(course_key)
    if listing is None:
        return HttpResponseRedirect(page_url("pending"))
    if not listing.is_paid:
        return HttpResponseRedirect(f"/campus/enrol/{course_key}/")

    # A verified payment that never got its enrolment (e.g. enrol failed after webhook): finish it.
    paid = Payment.objects.filter(user=request.user, course_key=course_key, status=Payment.STATUS_SUCCESS).first()
    if paid is not None:
        settle(paid)
        return HttpResponseRedirect(f"/campus/pay/callback/?{urlencode({'reference': paid.reference})}")

    payment = Payment.objects.create(
        user=request.user,
        course_key=course_key,
        institution=course_key.org,
        reference=f"EL-{uuid.uuid4().hex[:20].upper()}",
        amount=listing.price,
        currency=listing.currency,
        email=request.user.email,
    )
    try:
        data = _api(
            "POST",
            "/transaction/initialize",
            json={
                "email": payment.email,
                "amount": payment.amount_minor,
                "currency": payment.currency,
                "reference": payment.reference,
                "callback_url": f"{settings.LMS_ROOT_URL}/campus/pay/callback/",
                "metadata": {
                    "course_id": str(course_key),
                    "institution": course_key.org,
                    "username": request.user.username,
                    "cancel_action": f"{settings.LMS_ROOT_URL}/campus/pay/callback/?reference={payment.reference}",
                },
            },
        )
    except (PaystackError, requests.RequestException):
        log.exception("campus: Paystack initialize failed for %s", payment.reference)
        payment.status = Payment.STATUS_FAILED
        payment.gateway_response = "initialize failed"
        payment.save(update_fields=["status", "gateway_response", "modified"])
        return render_payment(request, "error", payment)
    return HttpResponseRedirect(data["authorization_url"])


@never_cache
@login_required
def callback_view(request):
    reference = request.GET.get("reference") or request.GET.get("trxref") or ""
    payment = Payment.objects.filter(reference=reference).first()
    if payment is None or payment.user_id != request.user.id:
        raise Http404
    if payment.status != Payment.STATUS_SUCCESS:
        try:
            payment = verify(payment)
        except (PaystackError, requests.RequestException):
            log.exception("campus: Paystack verify failed for %s", reference)
    if payment.status == Payment.STATUS_SUCCESS:
        return render_payment(request, "success", payment)
    if payment.status in (Payment.STATUS_INITIALIZED, Payment.STATUS_ABANDONED):
        return render_payment(request, "pending", payment)
    return render_payment(request, "failed", payment)


@csrf_exempt
@require_POST
def webhook_view(request):
    signature = request.headers.get("x-paystack-signature", "")
    try:
        expected = hmac.new(_secret().encode(), request.body, hashlib.sha512).hexdigest()
    except PaystackError:
        return HttpResponse(status=503)
    if not signature or not hmac.compare_digest(signature, expected):
        log.warning("campus: Paystack webhook with bad signature from %s", request.META.get("REMOTE_ADDR"))
        return HttpResponse(status=401)
    try:
        event = json.loads(request.body)
    except ValueError:
        return HttpResponseBadRequest("invalid json")
    data = event.get("data") or {}
    reference = data.get("reference", "")
    payment = Payment.objects.filter(reference=reference).first()
    if payment is None:
        log.info("campus: webhook for unknown reference %s (%s)", reference, event.get("event"))
        return HttpResponse(status=200)
    if event.get("event") == "charge.success":
        apply_verification(payment, data)
    elif event.get("event") in ("charge.failed",) and payment.status == Payment.STATUS_INITIALIZED:
        payment.status = Payment.STATUS_FAILED
        payment.gateway_response = str(data.get("gateway_response", ""))[:255]
        payment.save(update_fields=["status", "gateway_response", "modified"])
    return HttpResponse(status=200)


# ------------------------------------------------------------------------------ verification


def verify(payment):
    """Ask Paystack for the transaction's real state and apply it."""
    data = _api("GET", f"/transaction/verify/{payment.reference}")
    return apply_verification(payment, data)


def apply_verification(payment, data):
    """
    Apply a Paystack transaction payload (from verify or webhook). Success requires
    ``status == success`` and matching amount/currency; anything else is recorded as-is.
    """
    with transaction.atomic():
        payment = Payment.objects.select_for_update().get(pk=payment.pk)
        already = payment.status == Payment.STATUS_SUCCESS
        if not already:
            _apply_status(payment, data)
            payment.save()
    settle(payment)
    return payment


def _apply_status(payment, data):
    gateway_status = data.get("status", "")
    amount_ok = int(data.get("amount") or 0) == payment.amount_minor
    currency_ok = str(data.get("currency", "")).upper() == payment.currency
    payment.paystack_id = str(data.get("id", ""))[:32]
    payment.channel = str(data.get("channel", ""))[:32]
    payment.gateway_response = str(data.get("gateway_response", ""))[:255]
    if gateway_status == "success" and amount_ok and currency_ok:
        payment.status = Payment.STATUS_SUCCESS
        payment.paid_at = parse_datetime(data.get("paid_at") or "") or timezone.now()
    elif gateway_status == "success":
        payment.status = Payment.STATUS_FAILED
        payment.gateway_response = f"amount/currency mismatch: {data.get('amount')} {data.get('currency')}"[:255]
        log.error("campus: Paystack %s paid %s %s, expected %s %s", payment.reference, data.get("amount"), data.get("currency"), payment.amount_minor, payment.currency)
    elif gateway_status in ("failed", "reversed"):
        payment.status = Payment.STATUS_FAILED
    elif gateway_status == "abandoned":
        payment.status = Payment.STATUS_ABANDONED


def settle(payment):
    """Enrol and send the receipt for a successful payment; safe to call repeatedly."""
    if payment.status != Payment.STATUS_SUCCESS:
        return
    if not payment.enrolled:
        if payment.user.is_active:
            _enrol(payment.user, payment.course_key)
        else:
            log.warning("campus: payment %s verified but user %s is suspended; not enrolling", payment.reference, payment.user.username)
            return
        Payment.objects.filter(pk=payment.pk).update(enrolled=True, modified=timezone.now())
        payment.enrolled = True
        log.info("campus: paid enrolment %s → %s (%s)", payment.user.username, payment.course_key, payment.reference)
    emails.send_receipt(payment)


# ------------------------------------------------------------------------------------ pages

OUTCOMES = {
    "success": {
        "eyebrow": "Payment received",
        "title": "You're enrolled",
        "body": "Your payment has been confirmed and the course has been added to My learning. A receipt is on its way to your e-mail.",
        "primary": ("Start learning", "{course_url}"),
        "secondary": ("Go to My learning", "/dashboard"),
    },
    "pending": {
        "eyebrow": "Payment not completed",
        "title": "We haven't received your payment yet",
        "body": "The payment was not completed, so nothing has been charged and you are not enrolled. You can try again whenever you are ready.",
        "primary": ("Try again", "{pay_url}"),
        "secondary": ("Back to My learning", "/dashboard"),
    },
    "failed": {
        "eyebrow": "Payment unsuccessful",
        "title": "Your payment didn't go through",
        "body": "The payment was declined or could not be verified, so you have not been enrolled. If money left your account, contact billing with the reference below and we will resolve it.",
        "primary": ("Try again", "{pay_url}"),
        "secondary": ("Contact billing", "mailto:{billing_email}"),
    },
    "error": {
        "eyebrow": "Checkout unavailable",
        "title": "We couldn't start the payment",
        "body": "Our payment provider did not respond. Nothing has been charged. Please try again in a few minutes.",
        "primary": ("Try again", "{pay_url}"),
        "secondary": ("Back to My learning", "/dashboard"),
    },
}


def render_payment(request, outcome, payment):
    from openedx.core.djangoapps.content.course_overviews.models import CourseOverview  # pylint: disable=import-outside-toplevel

    page = OUTCOMES[outcome]
    overview = CourseOverview.get_from_id(payment.course_key)
    subs = {
        "{course_url}": _course_home(payment.course_key),
        "{pay_url}": f"/campus/pay/{payment.course_key}/",
        "{billing_email}": settings.MARKETPLACE_BILLING_EMAIL,
    }

    def resolve(link):
        label, href = link
        for k, v in subs.items():
            href = href.replace(k, v)
        return {"label": label, "href": href}

    context = {
        "code": f"payment-{outcome}",
        "page": {**page, "steps": [], "status": 200},
        "primary": resolve(page["primary"]),
        "secondary": resolve(page["secondary"]),
        "site_url": settings.CAMPUS_SITE_URL,
        "brand_url": settings.CAMPUS_BRAND_URL,
        "platform_name": settings.PLATFORM_NAME,
        "support_email": settings.CONTACT_EMAIL,
        "payment": payment,
        "amount": f"{Decimal(payment.amount):,.2f}",
        "course_title": overview.display_name,
    }
    return render(request, "campus_platform/status.html", context, status=200)
