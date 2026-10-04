"""
Unit tests for the public-form bot protection (plain Django; no Open edX needed):
  pip install "django>=4.2,<5" && python -m unittest discover -s platform-plugin-edulage/tests -t platform-plugin-edulage
"""
import pathlib
import re
import time
import unittest
from types import SimpleNamespace
from unittest import mock

import django
from django.conf import settings

if not settings.configured:
    settings.configure(
        SECRET_KEY="test-only-not-secret",
        CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
        USE_TZ=True,
    )
    django.setup()

from django.core.cache import cache  # noqa: E402

from edulage_platform import botguard, intake  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[2]

GOOD_NAMES = ["O'Neill", "Jean-Luc Picard", "José María", "Nnamdi Jr.", "Ọlá Adébáyọ̀", "Chukwuemeka Okonkwo",
              "Mary-Kate O’Brien", "Ngozi", "McDonald", "Zoë Saldaña"]
BAD_NAMES = [
    "Dear 🌟70k TL dev hediye seni bekliyor! https://bit.ly/4xwFNoF 🌟",
    "hSJEcmPHCVTponlBiizsCzEX", "pRJexHRWvNOstvNQWSasaPD", "visit bit.ly/abc", "win at example.com",
    "john@example.com", "John 2024", "www.spam", "<b>Bob</b>", "", "   ", "a" * 200,
]


def form(**overrides):
    data = {
        "institution_name": "University of Ibadan", "contact_name": "Ada Obi", "contact_email": "ada@ui.edu.ng",
        "country": "Nigeria", "contact_role": "Registrar", "website": "ui.edu.ng", "message": "Degrees",
        "form_token": botguard.issue_form_token(time.time() - 10),
    }
    data.update(overrides)
    return data


class NameRulesTest(unittest.TestCase):
    def test_ordinary_names_pass(self):
        for name in GOOD_NAMES:
            self.assertFalse(botguard.suspicious_person_name(name), name)

    def test_spam_link_and_random_names_rejected(self):
        for name in BAD_NAMES:
            self.assertTrue(botguard.suspicious_person_name(name), name)

    def test_institution_text(self):
        for ok in ["University of Ibadan", "Federal University of Technology, Owerri (FUTO)", "St. Mary's College 2",
                   "Université Cheikh Anta Diop", ""]:
            self.assertFalse(botguard.suspicious_text(ok), ok)
        for bad in ["Free money https://bit.ly/x", "visit spam.com now", "hSJEcmPHCVTponlBiizsCzEX", "<script>",
                    "mail me@x.org"]:
            self.assertTrue(botguard.suspicious_text(bad), bad)

    def test_keycloak_pattern_matches_rules_and_script(self):
        pattern = re.compile(botguard.KEYCLOAK_NAME_PATTERN)
        for name in ["O'Neill", "Jean-Luc", "José María", "Nnamdi Jr.", "Ọlá", "McDonald"]:
            self.assertIsNotNone(pattern.match(name), name)
        for name in ["hSJEcmPHCVTponlBiizsCzEX", "pRJexHRWvNOstvNQWSasaPD", "see https://bit.ly/4xwFNoF",
                     "bit.ly", "john@example.com", "John2"]:
            self.assertIsNone(pattern.match(name), name)
        script = (ROOT / "infra/keycloak/apply-realm-settings.py").read_text()
        block = re.search(r"NAME_PATTERN = \((.*?)\n\)", script, re.S).group(1)
        script_pattern = "".join(re.findall(r'r"(.*?)"', block))
        self.assertEqual(script_pattern, botguard.KEYCLOAK_NAME_PATTERN)


class FormTokenTest(unittest.TestCase):
    def test_states(self):
        now = time.time()
        self.assertEqual(botguard.check_form_token(botguard.issue_form_token(now - 10), now), botguard.TOKEN_OK)
        self.assertEqual(botguard.check_form_token(botguard.issue_form_token(now - 1), now), botguard.TOKEN_TOO_FAST)
        self.assertEqual(botguard.check_form_token(botguard.issue_form_token(now - 13 * 3600), now), botguard.TOKEN_EXPIRED)
        self.assertEqual(botguard.check_form_token("forged", now), botguard.TOKEN_INVALID)
        self.assertEqual(botguard.check_form_token(None, now), botguard.TOKEN_INVALID)


class PartnerRequestIntakeTest(unittest.TestCase):
    def setUp(self):
        cache.clear()
        self.record = mock.Mock(return_value=(SimpleNamespace(pk=7), True))

    def submit(self, data, ip="198.51.100.1"):
        return intake.partner_request(data, ip, self.record)

    def test_ordinary_request_recorded(self):
        code, body = self.submit(form(contact_name="Ọlá O'Neill-Adébáyọ̀"))
        self.assertEqual((code, body["status"]), (202, "received"))
        self.record.assert_called_once()
        self.assertEqual(self.record.call_args.args[0]["website"], "https://ui.edu.ng")

    def test_honeypot_fake_success_nothing_recorded(self):
        self.assertEqual(self.submit(form(company="Acme")), (202, {"status": "received"}))
        self.record.assert_not_called()

    def test_too_fast_fake_success_nothing_recorded(self):
        self.assertEqual(self.submit(form(form_token=botguard.issue_form_token())), (202, {"status": "received"}))
        self.record.assert_not_called()

    def test_missing_or_expired_token_rejected(self):
        self.assertEqual(self.submit(form(form_token=""))[0], 400)
        code, body = self.submit(form(form_token=botguard.issue_form_token(time.time() - 13 * 3600)))
        self.assertEqual((code, body["error"]), (400, "expired"))
        self.record.assert_not_called()

    def test_spam_names_rejected(self):
        for name in BAD_NAMES[:6]:
            code, body = self.submit(form(contact_name=name))
            self.assertEqual(code, 400, name)
            self.assertIn("contact_name", body["fields"])
        code, body = self.submit(form(institution_name="Get rich https://bit.ly/4xwFNoF"))
        self.assertIn("institution_name", body["fields"])
        self.record.assert_not_called()

    def test_per_email_limit(self):
        for i in range(intake.PER_EMAIL_DAY[1]):
            self.assertEqual(self.submit(form(), ip=f"203.0.113.{i}")[0], 202)
        self.assertEqual(self.submit(form(), ip="203.0.113.99")[0], 429)
        self.assertEqual(self.record.call_count, intake.PER_EMAIL_DAY[1])

    def test_per_ip_limit(self):
        for i in range(intake.PER_IP_DAY[1]):
            self.assertEqual(self.submit(form(contact_email=f"a{i}@ui.edu.ng"))[0], 202)
        self.assertEqual(self.submit(form(contact_email="other@ui.edu.ng"))[0], 429)

    def test_global_limit(self):
        for i in range(intake.GLOBAL_HOUR[1]):
            self.assertEqual(self.submit(form(contact_email=f"g{i}@ui.edu.ng"), ip=f"10.0.{i // 200}.{i % 200}")[0], 202)
        self.assertEqual(self.submit(form(contact_email="late@ui.edu.ng"), ip="10.9.9.9")[0], 429)


class RegistrationRefusalTest(unittest.TestCase):
    def setUp(self):
        cache.clear()

    def test_sso_registration_with_real_name_allowed(self):
        self.assertIsNone(botguard.registration_refusal("José María", "jm@example.org", "1.2.3.4", True, True))

    def test_direct_api_registration_refused_when_sso_required(self):
        self.assertEqual(botguard.registration_refusal("Ada Obi", "a@example.org", "1.2.3.4", False, True)[0], 403)

    def test_spam_name_refused(self):
        for name in BAD_NAMES[:3]:
            self.assertEqual(botguard.registration_refusal(name, "v@example.org", "1.2.3.4", True, True)[0], 400)

    def test_direct_registration_rate_limited(self):
        for i in range(botguard.REGISTRATION_PER_IP[1]):
            self.assertIsNone(botguard.registration_refusal("Ada Obi", f"u{i}@example.org", "1.2.3.4", False, False))
        self.assertEqual(botguard.registration_refusal("Ada Obi", "x@example.org", "1.2.3.4", False, False)[0], 429)


if __name__ == "__main__":
    unittest.main()
