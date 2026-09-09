"""
EduLage transactional e-mails, sent through Open edX's ACE pipeline (``django_email`` channel,
same SMTP settings as the stock platform mail) and rendered from
``templates/edulage_platform/edx_ace/<name>/email/``:

* ``welcome``      — first sign-in through EduLage created a learning account;
* ``enrolment``    — an admission was applied and the learner is enrolled in a course run;
* ``certificate``  — a certificate became downloadable (the institution awarded the credential,
                     EduLage recorded it and it can be verified on edulage.org).

Every stock Open edX e-mail (activation, password reset, course updates, instructor mail…)
extends ``ace_common/edx_ace/common/base_body.html``; ``templates/overrides`` replaces that frame
with the EduLage header/footer, so those keep their wording but wear the same brand.

Each notice is sent at most once per learner and subject (``SentEmail``); failures are logged and
never break the sign-in, enrolment or certificate flow that triggered them.
"""
import logging
from datetime import timezone

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils.formats import date_format
from edx_ace import ace
from edx_ace.recipient import Recipient
from opaque_keys.edx.keys import CourseKey

from .certificates import listing_context
from .models import SentEmail

log = logging.getLogger(__name__)

SITE_URL = "https://edulage.org"
VERIFY_URL = f"{SITE_URL}/verify/"


def brand_image_url(name):
    return f"{settings.EDULAGE_BRAND_URL}/images/{name}"


def lms_url(path=""):
    return f"{settings.LMS_ROOT_URL.rstrip('/')}/{path.lstrip('/')}"


def _message_types():
    from openedx.core.djangoapps.ace_common.message import BaseMessageType  # pylint: disable=import-outside-toplevel

    class EdulageMessage(BaseMessageType):
        APP_LABEL = "edulage_platform"

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.options["transactional"] = True
            self.options["from_address"] = settings.EDULAGE_EMAIL_FROM or settings.DEFAULT_FROM_EMAIL

    class Welcome(EdulageMessage):
        NAME = "welcome"

    class Enrolment(EdulageMessage):
        NAME = "enrolment"

    class Certificate(EdulageMessage):
        NAME = "certificate"

    return {
        SentEmail.KIND_WELCOME: Welcome,
        SentEmail.KIND_ENROLMENT: Enrolment,
        SentEmail.KIND_CERTIFICATE: Certificate,
    }


def _site():
    from crum import get_current_request  # pylint: disable=import-outside-toplevel
    from django.contrib.sites.models import Site  # pylint: disable=import-outside-toplevel

    request = get_current_request()
    if request is not None and hasattr(request, "site"):
        return request.site
    return Site.objects.get_current()


def _request_scope(user):
    """ACE template tags (link tracking, GA pixel) need a request; this supplies one outside a view/task."""
    from openedx.core.lib.celery.task_utils import emulate_http_request  # pylint: disable=import-outside-toplevel

    return emulate_http_request(site=_site(), user=user)


def base_context(user):
    from openedx.core.djangoapps.ace_common.template_context import get_base_template_context  # pylint: disable=import-outside-toplevel
    from openedx.core.djangoapps.site_configuration import helpers as configuration_helpers  # pylint: disable=import-outside-toplevel

    context = get_base_template_context(_site())
    context.update(
        {
            "site_url": SITE_URL,
            "programmes_url": f"{SITE_URL}/programmes",
            "help_url": f"{SITE_URL}/help",
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


def _course_context(course_key):
    from openedx.core.djangoapps.content.course_overviews.models import CourseOverview  # pylint: disable=import-outside-toplevel

    key = CourseKey.from_string(str(course_key))
    overview = CourseOverview.get_from_id(key)
    listing = listing_context(key)
    start = overview.start.astimezone(timezone.utc) if overview.start else None
    end = overview.end.astimezone(timezone.utc) if overview.end else None
    return {
        "course_key": str(key),
        "course_title": overview.display_name,
        "course_number": overview.display_number_with_default,
        "course_url": lms_url(f"learn/course/{key}/home"),
        "course_start": date_format(start, "j F Y") if start else "",
        "course_end": date_format(end, "j F Y") if end else "",
        "institution": listing.get("institution_name") or overview.display_org_with_default,
        "institution_url": listing.get("institution_url", ""),
        "programme_title": listing.get("programme_title", ""),
        "programme_url": listing.get("programme_url", ""),
        "classification": listing.get("classification_label", "Course"),
        "credential": listing.get("credential", ""),
        "delivery_mode": listing.get("delivery_mode", ""),
    }


def welcome_context(user):
    context = base_context(user)
    context.update({"account_url": lms_url("account/settings")})
    return context


def enrolment_context(user, course_key):
    context = base_context(user)
    context.update(_course_context(course_key))
    return context


def certificate_context(user, course_key, verify_uuid):
    context = base_context(user)
    context.update(_course_context(course_key))
    context.update(
        {
            "certificate_url": lms_url(f"certificates/{verify_uuid}"),
            "verify_url": f"{VERIFY_URL}{verify_uuid}",
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


def _send(user, kind, reference, context):
    if not user.email or not user.is_active:
        return False
    if not _record(user, kind, reference):
        return False
    try:
        with _request_scope(user):
            ace.send(_personalized(user, kind, context))
    except Exception:  # pylint: disable=broad-except
        log.exception("edulage: %s e-mail to %s (%s) failed", kind, user.username, reference)
        SentEmail.objects.filter(user=user, kind=kind, reference=reference).delete()
        return False
    log.info("edulage: sent %s e-mail to %s %s", kind, user.username, reference)
    return True


def send_welcome(user):
    return _send(user, SentEmail.KIND_WELCOME, "", welcome_context(user))


def send_enrolment(user, course_key):
    return _send(user, SentEmail.KIND_ENROLMENT, str(course_key), enrolment_context(user, course_key))


def send_certificate(user, course_key, verify_uuid):
    return _send(
        user, SentEmail.KIND_CERTIFICATE, str(course_key), certificate_context(user, course_key, verify_uuid)
    )


def _personalized(user, kind, context):
    from openedx.core.djangoapps.lang_pref import LANGUAGE_KEY  # pylint: disable=import-outside-toplevel
    from openedx.core.djangoapps.user_api.preferences.api import get_user_preference  # pylint: disable=import-outside-toplevel

    return _message_types()[kind]().personalize(
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
