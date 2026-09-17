"""
Open edX → control-plane event delivery (transactional outbox + signed webhooks).

Producers call ``emit()`` inside the transaction that records the fact. A Celery task (or the
``campus_events`` management command) delivers pending rows in sequence order to
``CAMPUS_WEBHOOK_URL`` as::

    POST <CAMPUS_WEBHOOK_URL>
    Content-Type: application/json
    X-Campus-Event: <event_type>
    X-Campus-Event-Id: <uuid>
    X-Campus-Sequence: <sequence>
    X-Campus-Timestamp: <unix seconds>
    X-Campus-Signature: v1=<hex hmac-sha256(secret, "<timestamp>.<body>")>

    {"id": "...", "type": "enrolment.created", "version": 1, "sequence": 42, "occurred": "...",
     "institution": "UNIA", "course_id": "course-v1:...", "sub": "...", "data": {...}}

Receivers must treat ``id`` as the idempotency key and may use ``sequence`` to detect gaps and
order events; any 2xx acknowledges. Failures retry with exponential back-off (1 min … ~17 h);
after ``OutboxEvent.MAX_ATTEMPTS`` the row is parked as ``failed`` for audited replay.
``GET /campus/api/v1/events/?since=<sequence>`` lets the control plane reconcile by pulling.

Event types (v1): enrolment.created, enrolment.deactivated, course.completed (grade passed),
certificate.issued, certificate.revoked, admission.applied, user.suspended, user.reactivated,
institution.provisioned.
"""
import hashlib
import hmac
import json
import logging
import time
import uuid
from datetime import timedelta

import requests
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import OutboxEvent

log = logging.getLogger(__name__)

SIGNATURE_VERSION = "v1"
BACKOFF_SECONDS = [60, 300, 900, 1800, 3600, 7200, 14400, 28800]


def configured():
    return bool(settings.CAMPUS_WEBHOOK_URL and settings.CAMPUS_WEBHOOK_SECRET)


def emit(event_type, data, institution="", course_key=None, sub="", version=1, occurred=None):
    """Queue an event; delivery is scheduled after the surrounding transaction commits."""
    event = OutboxEvent.objects.create(
        uuid=uuid.uuid4(),
        event_type=event_type,
        version=version,
        institution=institution or (course_key.org if course_key else ""),
        course_key=course_key,
        identity_sub=sub or "",
        payload=data,
        occurred=occurred or timezone.now(),
        next_attempt=timezone.now(),
    )
    transaction.on_commit(schedule_delivery)
    return event


def schedule_delivery():
    if not configured():
        return
    try:
        from .tasks import deliver_pending  # pylint: disable=import-outside-toplevel

        deliver_pending.delay()
    except ImportError:  # celery not available (management/test contexts)
        deliver_pending_now()


def serialize(event):
    return {
        "id": str(event.uuid),
        "type": event.event_type,
        "version": event.version,
        "sequence": event.sequence,
        "occurred": event.occurred.isoformat(),
        "institution": event.institution,
        "course_id": str(event.course_key) if event.course_key else None,
        "sub": event.identity_sub or None,
        "data": event.payload,
    }


def sign(secret, timestamp, body):
    digest = hmac.new(secret.encode(), f"{timestamp}.{body}".encode(), hashlib.sha256).hexdigest()
    return f"{SIGNATURE_VERSION}={digest}"


def verify_signature(secret, timestamp, body, header, tolerance=300):
    """For receivers (and tests): constant-time check plus replay window on the timestamp."""
    try:
        if abs(time.time() - int(timestamp)) > tolerance:
            return False
    except (TypeError, ValueError):
        return False
    return hmac.compare_digest(sign(secret, timestamp, body), header or "")


def deliver(event):
    """Attempt one delivery; updates the row and returns True on 2xx."""
    body = json.dumps(serialize(event), separators=(",", ":"), sort_keys=True)
    timestamp = str(int(time.time()))
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "platform-plugin-campus/1.0",
        "X-Campus-Event": event.event_type,
        "X-Campus-Event-Id": str(event.uuid),
        "X-Campus-Sequence": str(event.sequence),
        "X-Campus-Timestamp": timestamp,
        "X-Campus-Signature": sign(settings.CAMPUS_WEBHOOK_SECRET, timestamp, body),
    }
    event.attempts += 1
    try:
        response = requests.post(settings.CAMPUS_WEBHOOK_URL, data=body, headers=headers, timeout=10)
        ok = 200 <= response.status_code < 300
        error = "" if ok else f"HTTP {response.status_code}: {response.text[:500]}"
    except requests.RequestException as exc:
        ok, error = False, str(exc)[:500]
    if ok:
        event.status = OutboxEvent.STATUS_DELIVERED
        event.delivered = timezone.now()
        event.next_attempt = None
        event.last_error = ""
    elif event.attempts >= OutboxEvent.MAX_ATTEMPTS:
        event.status = OutboxEvent.STATUS_FAILED
        event.next_attempt = None
        event.last_error = error
        log.error("campus events: %s parked after %s attempts: %s", event, event.attempts, error)
    else:
        delay = BACKOFF_SECONDS[min(event.attempts - 1, len(BACKOFF_SECONDS) - 1)]
        event.next_attempt = timezone.now() + timedelta(seconds=delay)
        event.last_error = error
    event.save(update_fields=["status", "attempts", "next_attempt", "delivered", "last_error"])
    return ok


def deliver_pending_now(limit=200):
    """Deliver due events in sequence order; stop at the first failure to preserve ordering."""
    if not configured():
        return 0
    due = OutboxEvent.objects.filter(status=OutboxEvent.STATUS_PENDING, next_attempt__lte=timezone.now()).order_by("sequence")[:limit]
    delivered = 0
    for event in due:
        if not deliver(event):
            break
        delivered += 1
    return delivered


def replay(event_ids, actor=None):
    """Re-queue failed/delivered events for delivery (audited); returns the number re-queued."""
    from . import identity  # pylint: disable=import-outside-toplevel

    count = OutboxEvent.objects.filter(uuid__in=event_ids).update(
        status=OutboxEvent.STATUS_PENDING, attempts=0, next_attempt=timezone.now(), last_error="",
    )
    identity.audit("events_replayed", user=actor, detail=f"{count} events: {', '.join(str(i) for i in event_ids)[:900]}", actor="events")
    transaction.on_commit(schedule_delivery)
    return count
