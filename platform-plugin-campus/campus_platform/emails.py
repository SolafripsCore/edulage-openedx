"""
Campus transactional e-mails, sent through Open edX's ACE pipeline (``django_email`` channel,
same SMTP settings as the stock platform mail) and rendered from
``templates/campus_platform/edx_ace/<name>/email/``:

* ``welcome``      — first sign-in through the identity provider created a learning account;
* ``enrolment``    — an admission was applied and the learner is enrolled in a course run;
* ``certificate``  — a certificate became downloadable (the institution awarded the credential,
                     the platform recorded it and it can be verified on the product site);
* ``invitation``   — an institution administrator invited someone to a staff role (plain Django
                     mail: the invitee may not have an LMS account yet, so ACE cannot address it).

Every stock Open edX e-mail (activation, password reset, course updates, instructor mail…)
extends ``ace_common/edx_ace/common/base_body.html``; ``templates/overrides`` replaces that frame
with the product header/footer, so those keep their wording but wear the same brand.

Each notice is sent at most once per learner and subject (``SentEmail``); failures are logged and
never break the sign-in, enrolment or certificate flow that triggered them.
"""
import logging
from contextlib import contextmanager
from datetime import timezone

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db import IntegrityError, transaction
from django.template.loader import render_to_string
from django.utils.formats import date_format
from edx_ace import ace
from edx_ace.recipient import Recipient
from opaque_keys.edx.keys import CourseKey

from . import hooks
from .models import SentEmail

log = logging.getLogger(__name__)



def site_url():
    """Public site of the product running this deployment (control-plane portal)."""
    return settings.CAMPUS_SITE_URL.rstrip("/")


def verify_url(uuid):
    return f"{settings.CAMPUS_VERIFY_URL.rstrip('/')}/{uuid}"


def brand_image_url(name):
    return f"{settings.CAMPUS_BRAND_URL}/images/{name}"


def lms_url(path=""):
    return f"{settings.LMS_ROOT_URL.rstrip('/')}/{path.lstrip('/')}"


# kind -> (ACE message NAME, Django app label owning the ``edx_ace/<NAME>`` templates).
# Product layers add their own kinds with ``register_message_type``.
_MESSAGE_REGISTRY = {
    SentEmail.KIND_WELCOME: ("welcome", "campus_platform"),
    SentEmail.KIND_ENROLMENT: ("enrolment", "campus_platform"),
    SentEmail.KIND_CERTIFICATE: ("certificate", "campus_platform"),
}


def register_message_type(kind, name, app_label):
    _MESSAGE_REGISTRY[kind] = (name, app_label)


def message_type(kind):
    from openedx.core.djangoapps.ace_common.message import BaseMessageType  # pylint: disable=import-outside-toplevel

    name, app_label = _MESSAGE_REGISTRY[kind]

    class CampusMessage(BaseMessageType):
        NAME = name
        APP_LABEL = app_label

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.options["transactional"] = True
            self.options["from_address"] = settings.CAMPUS_EMAIL_FROM or settings.DEFAULT_FROM_EMAIL

    return CampusMessage


def _site():
    from crum import get_current_request  # pylint: disable=import-outside-toplevel
    from django.contrib.sites.models import Site  # pylint: disable=import-outside-toplevel

    request = get_current_request()
    if request is not None and hasattr(request, "site"):
        return request.site
    return Site.objects.get_current()


@contextmanager
def _request_scope(user):
    """
    ACE template tags (link tracking, GA pixel) need a request; this supplies one outside a
    view/task and leaves a real in-flight request (crum) untouched, since emulate_http_request
    clears it on exit.
    """
    from crum import get_current_request  # pylint: disable=import-outside-toplevel
    from openedx.core.lib.celery.task_utils import emulate_http_request  # pylint: disable=import-outside-toplevel

    if get_current_request() is not None:
        yield
        return
    with emulate_http_request(site=_site(), user=user):
        yield


def base_context(user):
    from openedx.core.djangoapps.ace_common.template_context import get_base_template_context  # pylint: disable=import-outside-toplevel
    from openedx.core.djangoapps.site_configuration import helpers as configuration_helpers  # pylint: disable=import-outside-toplevel

    context = get_base_template_context(_site())
    context.update(
        {
            "site_url": site_url(),
            "platform_name": settings.PLATFORM_NAME,
            "programmes_url": f"{site_url()}/programmes",
            "help_url": f"{site_url()}/help",
            "my_learning_url": lms_url("dashboard"),
            "learner_name": _display_name(user),
            "learner_email": user.email,
            "support_email": configuration_helpers.get_value("CONTACT_EMAIL", settings.CONTACT_EMAIL),
        }
    )
    return context


def _display_name(user):
    from common.djangoapps.student.models import UserProfile  # pylint: disable=import-outside-toplevel

    profile = UserProfile.objects.filter(user=user).first()
    return (profile.name if profile else "") or user.first_name or user.username


def course_context(course_key):
    from openedx.core.djangoapps.content.course_overviews.models import CourseOverview  # pylint: disable=import-outside-toplevel

    key = CourseKey.from_string(str(course_key))
    overview = CourseOverview.get_from_id(key)
    listing = hooks.course_metadata(key)
    start = overview.start.astimezone(timezone.utc) if overview.start else None
    end = overview.end.astimezone(timezone.utc) if overview.end else None
    return {
        "course_key": str(key),
        "course_title": overview.display_name,
        "course_number": overview.display_number_with_default,
        "course_url": f"{settings.LEARNING_MICROFRONTEND_URL}/course/{key}/home",
        "course_start": date_format(start, "j F Y") if start else "",
        "course_end": date_format(end, "j F Y") if end else "",
        "institution": listing.get("institution_name") or overview.display_org_with_default,
        "institution_url": listing.get("institution_url", ""),
        "programme_title": listing.get("programme_title", ""),
        "programme_url": listing.get("programme_url", ""),
        "classification": listing.get("classification_label", "Course"),
        "credential": listing.get("credential", ""),
        "delivery_mode": listing.get("delivery_mode", ""),
        "open_enrolment": listing.get("enrolment_policy", "admission") != "admission",
    }


def welcome_context(user):
    context = base_context(user)
    context.update({"account_url": lms_url("account/settings")})
    return context


def enrolment_context(user, course_key):
    context = base_context(user)
    context.update(course_context(course_key))
    return context


def certificate_context(user, course_key, verify_uuid):
    context = base_context(user)
    context.update(course_context(course_key))
    context.update(
        {
            "certificate_url": lms_url(f"certificates/{verify_uuid}"),
            "verify_url": verify_url(verify_uuid),
            "credential_id": verify_uuid,
            "credential": context["credential"] or "Certificate",
        }
    )
    return context


def _record(user, kind, reference):
    """Claim the (user, kind, reference) slot; False if this notice was already sent."""
    try:
        with transaction.atomic():
            SentEmail.objects.create(user=user, kind=kind, reference=reference)
    except IntegrityError:
        return False
    return True


def send(user, kind, reference, context):
    if not user.email or not user.is_active:
        return False
    if not _record(user, kind, reference):
        return False
    try:
        with _request_scope(user):
            ace.send(_personalized(user, kind, context))
    except Exception:  # pylint: disable=broad-except
        log.exception("campus: %s e-mail to %s (%s) failed", kind, user.username, reference)
        SentEmail.objects.filter(user=user, kind=kind, reference=reference).delete()
        return False
    log.info("campus: sent %s e-mail to %s %s", kind, user.username, reference)
    return True


def send_welcome(user):
    return send(user, SentEmail.KIND_WELCOME, "", welcome_context(user))


def send_enrolment(user, course_key):
    return send(user, SentEmail.KIND_ENROLMENT, str(course_key), enrolment_context(user, course_key))


def send_certificate(user, course_key, verify_uuid):
    return send(
        user, SentEmail.KIND_CERTIFICATE, str(course_key), certificate_context(user, course_key, verify_uuid)
    )


def _personalized(user, kind, context):
    from openedx.core.djangoapps.lang_pref import LANGUAGE_KEY  # pylint: disable=import-outside-toplevel
    from openedx.core.djangoapps.user_api.preferences.api import get_user_preference  # pylint: disable=import-outside-toplevel

    return message_type(kind)().personalize(
        recipient=Recipient(lms_user_id=user.id, email_address=user.email),
        language=get_user_preference(user, LANGUAGE_KEY) or settings.LANGUAGE_CODE,
        user_context=context,
    )


def render_preview(user, kind, context):
    """(subject, html, text) exactly as ACE would send it, for the preview command and design review."""
    from edx_ace.channel.django_email import DjangoEmailChannel  # pylint: disable=import-outside-toplevel
    from edx_ace.renderers import EmailRenderer  # pylint: disable=import-outside-toplevel

    with _request_scope(user):
        rendered = EmailRenderer().render(DjangoEmailChannel(), _personalized(user, kind, context))
    html = f"<!DOCTYPE html><html><head>{rendered.head_html}</head><body>{rendered.body_html}</body></html>"
    return rendered.subject.strip(), html, rendered.body


def send_staff_invitation(invitation, institution_name, accept_url):
    """E-mail the invitee a link to accept a staff role; True when handed to the mail backend."""
    context = {
        "invitation": invitation,
        "institution_name": institution_name,
        "accept_url": accept_url,
        "inviter": _display_name(invitation.invited_by) if invitation.invited_by else "An administrator",
        "site_url": site_url(),
        "platform_name": settings.PLATFORM_NAME,
        "help_url": f"{site_url()}/help",
        "brand_url": settings.CAMPUS_BRAND_URL,
        "expires": date_format(invitation.expires, "j F Y"),
    }
    subject = f"You're invited to join {institution_name} on {settings.PLATFORM_NAME} as {invitation.role_label}"
    try:
        message = EmailMultiAlternatives(
            subject=subject,
            body=render_to_string("campus_platform/invitation_email.txt", context),
            from_email=settings.CAMPUS_EMAIL_FROM or settings.DEFAULT_FROM_EMAIL,
            to=[invitation.email],
        )
        message.attach_alternative(render_to_string("campus_platform/invitation_email.html", context), "text/html")
        message.send()
    except Exception:  # pylint: disable=broad-except
        log.exception("campus: invitation e-mail to %s failed", invitation.email)
        return False
    log.info("campus: sent invitation e-mail to %s (%s)", invitation.email, invitation.claim)
    return True


def send_notice(to, subject, eyebrow, heading, paragraphs, details=(), action_url="", action_label="", footnote=""):
    """Branded transactional notice (text + HTML) to one or more addresses; True when handed to the backend."""
    context = {
        "eyebrow": eyebrow,
        "heading": heading,
        "paragraphs": paragraphs,
        "details": list(details),
        "action_url": action_url,
        "action_label": action_label,
        "footnote": footnote,
        "site_url": site_url(),
        "platform_name": settings.PLATFORM_NAME,
        "help_url": f"{site_url()}/help",
        "brand_url": settings.CAMPUS_BRAND_URL,
    }
    try:
        message = EmailMultiAlternatives(
            subject=subject,
            body=render_to_string("campus_platform/notice_email.txt", context),
            from_email=settings.CAMPUS_EMAIL_FROM or settings.DEFAULT_FROM_EMAIL,
            to=list(to),
        )
        message.attach_alternative(render_to_string("campus_platform/notice_email.html", context), "text/html")
        message.send()
    except Exception:  # pylint: disable=broad-except
        log.exception("campus: notice e-mail %r to %s failed", subject, to)
        return False
    return True
