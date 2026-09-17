"""Unit tests for the parts of the core that run without Open edX (hooks, provisioning helpers, events)."""
import json
import time
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from opaque_keys.edx.keys import CourseKey

from campus_platform import events, hooks, provisioning
from campus_platform.models import OutboxEvent

COURSE = CourseKey.from_string("course-v1:UNIA+CS101+2026")


class HooksTests(TestCase):
    def test_defaults_require_admission_and_fall_back_to_org(self):
        self.assertEqual(hooks.enrolment_policy(None, COURSE), hooks.POLICY_ADMISSION)
        data = hooks.course_metadata(COURSE)
        self.assertEqual(data["institution"], "UNIA")
        self.assertEqual(data["enrolment_policy"], hooks.POLICY_ADMISSION)
        self.assertEqual(set(data), set(hooks.COURSE_METADATA_FIELDS))

    @override_settings(
        CAMPUS_ENROLMENT_POLICY_PROVIDER="tests.test_core.open_policy",
        CAMPUS_COURSE_METADATA_PROVIDER="tests.test_core.metadata",
    )
    def test_providers_override(self):
        self.assertEqual(hooks.enrolment_policy(None, COURSE), hooks.POLICY_OPEN)
        self.assertEqual(hooks.course_metadata(COURSE)["programme_title"], "Provided")


def open_policy(user, course_key):
    return hooks.POLICY_OPEN


def metadata(course_key):
    return {"programme_title": "Provided"}


class ProvisioningTests(TestCase):
    def test_code_suggestion_and_validation(self):
        self.assertEqual(provisioning.suggest_code("University of Abuja"), "UOA")
        self.assertEqual(provisioning.suggest_code("Yaba College of Technology"), "YCOT")
        self.assertTrue(provisioning.CODE_RE.match("UNIA"))
        self.assertFalse(provisioning.CODE_RE.match("unia"))
        self.assertFalse(provisioning.CODE_RE.match("U"))
        self.assertIn("STUDIO", provisioning.RESERVED_CODES)

    def test_templates(self):
        self.assertEqual(provisioning.tenant_host("UNIA"), "unia.learn.example.org")
        self.assertEqual(provisioning.tenant_platform_name("UNIA", "University of Abuja"), "University of Abuja on Example Campus")

    @override_settings(CAMPUS_TENANT_HOST_TEMPLATE="{code}-ecampus.edusite.ng", CAMPUS_TENANT_PLATFORM_NAME="{name} eCampus")
    def test_items_style_templates(self):
        cfg = provisioning.lms_configs("UNIA", "University of Abuja")
        self.assertEqual(cfg["LMS_BASE"], "unia-ecampus.edusite.ng")
        self.assertEqual(cfg["LMS_ROOT_URL"], "https://unia-ecampus.edusite.ng")
        self.assertEqual(cfg["PLATFORM_NAME"], "University of Abuja eCampus")
        self.assertEqual(cfg["course_org_filter"], ["UNIA"])
        self.assertIsNone(cfg["SESSION_COOKIE_DOMAIN"])
        self.assertNotIn("MKTG_URLS", cfg)

    @override_settings(CAMPUS_TENANT_MKTG_ROOT="https://portal.example.org/{code}")
    def test_optional_landing(self):
        cfg = provisioning.lms_configs("UNIA", "University of Abuja")
        self.assertEqual(cfg["MKTG_URLS"]["ROOT"], "https://portal.example.org/unia")


class EventsTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create(username="ada", email="ada@example.org")

    def test_signature_round_trip(self):
        ts = str(int(time.time()))
        sig = events.sign("s", ts, "{}")
        self.assertTrue(sig.startswith("v1="))
        self.assertTrue(events.verify_signature("s", ts, "{}", sig))
        self.assertFalse(events.verify_signature("other", ts, "{}", sig))
        self.assertFalse(events.verify_signature("s", str(int(time.time()) - 3600), "{}", events.sign("s", str(int(time.time()) - 3600), "{}")))

    def test_emit_records_row_with_institution_from_course(self):
        with mock.patch.object(events, "schedule_delivery"):
            e = events.emit("enrolment.created", {"username": "ada"}, course_key=COURSE, sub="abc")
        self.assertEqual(e.institution, "UNIA")
        self.assertEqual(e.status, OutboxEvent.STATUS_PENDING)
        body = events.serialize(e)
        self.assertEqual(body["type"], "enrolment.created")
        self.assertEqual(body["course_id"], str(COURSE))
        self.assertEqual(body["sub"], "abc")
        self.assertEqual(body["version"], 1)

    def _emit(self, n=1):
        with mock.patch.object(events, "schedule_delivery"):
            return [events.emit(f"t.{i}", {"i": i}, institution="UNIA") for i in range(n)]

    def test_delivery_success_signs_and_marks_delivered(self):
        (e,) = self._emit()
        with mock.patch.object(events.requests, "post") as post:
            post.return_value = mock.Mock(status_code=200, text="")
            self.assertTrue(events.deliver(e))
        _, kwargs = post.call_args
        headers, body = kwargs["headers"], kwargs["data"]
        self.assertEqual(headers["X-Campus-Event-Id"], str(e.uuid))
        self.assertTrue(events.verify_signature("test-secret", headers["X-Campus-Timestamp"], body, headers["X-Campus-Signature"]))
        self.assertEqual(json.loads(body)["sequence"], e.sequence)
        e.refresh_from_db()
        self.assertEqual(e.status, OutboxEvent.STATUS_DELIVERED)
        self.assertEqual(e.attempts, 1)

    def test_failure_backs_off_then_dead_letters(self):
        (e,) = self._emit()
        with mock.patch.object(events.requests, "post") as post:
            post.return_value = mock.Mock(status_code=503, text="down")
            self.assertFalse(events.deliver(e))
            e.refresh_from_db()
            self.assertEqual(e.status, OutboxEvent.STATUS_PENDING)
            self.assertIsNotNone(e.next_attempt)
            self.assertIn("503", e.last_error)
            for _ in range(OutboxEvent.MAX_ATTEMPTS - 1):
                events.deliver(e)
        e.refresh_from_db()
        self.assertEqual(e.status, OutboxEvent.STATUS_FAILED)
        self.assertIsNone(e.next_attempt)

    def test_pending_delivery_preserves_order_and_stops_on_failure(self):
        first, second, third = self._emit(3)
        with mock.patch.object(events.requests, "post") as post:
            post.side_effect = [mock.Mock(status_code=200, text=""), mock.Mock(status_code=500, text="")]
            self.assertEqual(events.deliver_pending_now(), 1)
        for e in (first, second, third):
            e.refresh_from_db()
        self.assertEqual(first.status, OutboxEvent.STATUS_DELIVERED)
        self.assertEqual(second.status, OutboxEvent.STATUS_PENDING)
        self.assertEqual(second.attempts, 1)
        self.assertEqual(third.attempts, 0)

    @override_settings(CAMPUS_WEBHOOK_URL="")
    def test_unconfigured_records_but_does_not_deliver(self):
        self._emit()
        with mock.patch.object(events.requests, "post") as post:
            self.assertEqual(events.deliver_pending_now(), 0)
        post.assert_not_called()

    def test_replay_requeues(self):
        (e,) = self._emit()
        OutboxEvent.objects.filter(pk=e.pk).update(status=OutboxEvent.STATUS_FAILED, attempts=8, next_attempt=None)
        with mock.patch.object(events, "schedule_delivery"), mock.patch("campus_platform.identity.audit"):
            self.assertEqual(events.replay([str(e.uuid)], actor=self.user), 1)
        e.refresh_from_db()
        self.assertEqual((e.status, e.attempts), (OutboxEvent.STATUS_PENDING, 0))
