"""Marketplace layer: policy hooks and Studio settings parsing."""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from opaque_keys.edx.keys import CourseKey

from campus_marketplace import catalogue, policy
from campus_marketplace.models import CourseListing, Payment
from campus_platform import hooks

COURSE = CourseKey.from_string("course-v1:UNIA+CS101+2026")


class PolicyTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create(username="ada", email="ada@example.org")

    def test_no_listing_means_admission(self):
        self.assertEqual(policy.enrolment_policy(self.user, COURSE), hooks.POLICY_ADMISSION)
        self.assertIsNone(policy.course_metadata(COURSE))

    def test_open_free(self):
        CourseListing.objects.create(course_key=COURSE, institution="UNIA", institution_name="UNIA", enrolment_policy=CourseListing.POLICY_OPEN_FREE)
        self.assertEqual(policy.enrolment_policy(self.user, COURSE), hooks.POLICY_OPEN)

    def test_open_paid_requires_successful_payment(self):
        CourseListing.objects.create(
            course_key=COURSE, institution="UNIA", institution_name="UNIA",
            enrolment_policy=CourseListing.POLICY_OPEN_PAID, price=Decimal("25000"),
        )
        self.assertTrue(policy.enrolment_policy(self.user, COURSE).startswith("blocked:"))
        Payment.objects.create(user=self.user, course_key=COURSE, institution="UNIA", reference="R1", amount=Decimal("25000"), status=Payment.STATUS_SUCCESS)
        self.assertEqual(policy.enrolment_policy(self.user, COURSE), hooks.POLICY_OPEN)
        data = policy.course_metadata(COURSE)
        self.assertEqual(data["price"], "25000.00")
        self.assertTrue(set(hooks.COURSE_METADATA_FIELDS) <= set(data))


class StudioSettingsTests(TestCase):
    def test_marketplace_key_and_legacy_key(self):
        new = catalogue.parse_marketplace_settings({"marketplace": {"enrolment_policy": "paid", "price": 25000}})
        old = catalogue.parse_marketplace_settings({"edulage": {"enrolment_policy": "open-free"}})
        self.assertEqual(new["enrolment_policy"], "open_paid")
        self.assertEqual(old["enrolment_policy"], "open_free")
        self.assertIsNone(catalogue.parse_marketplace_settings({}))
        self.assertIsNone(catalogue.parse_marketplace_settings({"marketplace": {"enrolment_policy": "bogus"}}))
