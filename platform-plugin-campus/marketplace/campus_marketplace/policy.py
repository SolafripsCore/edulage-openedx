"""Marketplace implementations of the core hooks (``campus_platform.hooks``)."""
from campus_platform import hooks

from .models import CourseListing, Payment


def enrolment_policy(user, course_key):
    listing = CourseListing.objects.filter(course_key=course_key).first()
    policy = listing.enrolment_policy if listing else CourseListing.POLICY_ADMISSION
    if policy == CourseListing.POLICY_OPEN_FREE:
        return hooks.POLICY_OPEN
    if policy == CourseListing.POLICY_OPEN_PAID:
        if Payment.objects.filter(user=user, course_key=course_key, status=Payment.STATUS_SUCCESS).exists():
            return hooks.POLICY_OPEN
        return "blocked:This course is a paid open-enrolment course. Complete payment to enrol."
    return hooks.POLICY_ADMISSION


def course_metadata(course_key):
    listing = CourseListing.objects.filter(course_key=course_key).first()
    if listing is None:
        return None
    data = hooks.default_course_metadata(course_key)
    data.update(listing.as_dict())
    return data
