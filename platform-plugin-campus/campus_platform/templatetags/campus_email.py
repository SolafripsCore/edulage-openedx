"""Template helpers for the e-mail frame (``templates/overrides/ace_common``)."""
from django import template
from django.conf import settings

from ..emails import brand_image_url, site_url

register = template.Library()


@register.simple_tag
def lms_absolute(path):
    """Absolute LMS URL for the relative paths Open edX puts in e-mail contexts (e.g. ``/dashboard``)."""
    if not path or path.startswith(("http://", "https://")):
        return path or settings.LMS_ROOT_URL
    return f"{settings.LMS_ROOT_URL.rstrip('/')}/{path.lstrip('/')}"


@register.simple_tag
def campus_site_url(path=""):
    return f"{site_url()}/{path.lstrip('/')}" if path else site_url()


@register.simple_tag
def campus_brand_image(name):
    return brand_image_url(name)
