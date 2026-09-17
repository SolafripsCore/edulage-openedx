"""Marketplace e-mails: Paystack payment receipt (``edx_ace/receipt`` templates in this app)."""
from django.conf import settings
from django.utils import timezone
from django.utils.formats import date_format

from campus_platform import emails as core

KIND_RECEIPT = "receipt"
core.register_message_type(KIND_RECEIPT, "receipt", "campus_marketplace")


def receipt_context(payment):
    context = core.base_context(payment.user)
    context.update(core.course_context(payment.course_key))  # pylint: disable=protected-access
    paid_at = payment.paid_at.astimezone(timezone.utc) if payment.paid_at else None
    context.update(
        {
            "reference": payment.reference,
            "amount": f"{payment.amount:,.2f}",
            "currency": payment.currency,
            "channel": payment.channel,
            "paid_at": date_format(paid_at, "j F Y, H:i") if paid_at else "",
            "billing_email": settings.MARKETPLACE_BILLING_EMAIL,
        }
    )
    return context


def send_receipt(payment):
    return core.send(payment.user, KIND_RECEIPT, payment.reference, receipt_context(payment))


send_notice = core.send_notice
send_staff_invitation = core.send_staff_invitation
