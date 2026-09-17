"""
Extension points through which an optional product layer (``campus_marketplace``, or a control
plane's own plugin) refines core behaviour. The core never imports product code; providers are
dotted paths in Django settings and resolved lazily.

``CAMPUS_ENROLMENT_POLICY_PROVIDER``  callable(user, course_key) -> "admission" | "open" | "blocked:<message>"
``CAMPUS_COURSE_METADATA_PROVIDER``   callable(course_key) -> dict (see ``COURSE_METADATA_FIELDS``)

Without providers every run requires an Admission and course metadata falls back to the
Open edX organisation.
"""
from django.conf import settings
from django.utils.module_loading import import_string
from opaque_keys import InvalidKeyError
from opaque_keys.edx.keys import CourseKey

POLICY_ADMISSION = "admission"
POLICY_OPEN = "open"

COURSE_METADATA_FIELDS = (
    "institution", "institution_name", "institution_logo", "institution_url", "programme_title",
    "programme_url", "classification", "classification_label", "credential", "delivery_mode",
    "enrolment_policy", "price", "currency",
)


def _provider(path):
    return import_string(path) if path else None


def enrolment_policy(user, course_key):
    provider = _provider(settings.CAMPUS_ENROLMENT_POLICY_PROVIDER)
    return provider(user, course_key) if provider else POLICY_ADMISSION


def default_course_metadata(course_key):
    try:
        key = CourseKey.from_string(str(course_key))
    except InvalidKeyError:
        return {}
    data = {f: "" for f in COURSE_METADATA_FIELDS}
    data.update(
        institution=key.org, classification="course", classification_label="Course",
        enrolment_policy=POLICY_ADMISSION, price="0.00", currency="NGN",
    )
    return data


def course_metadata(course_key):
    provider = _provider(settings.CAMPUS_COURSE_METADATA_PROVIDER)
    data = provider(course_key) if provider else None
    return data if data else default_course_metadata(course_key)
