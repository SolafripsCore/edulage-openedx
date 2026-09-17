"""
Render or send a transactional e-mail for a learner.

    ./manage.py lms campus_email welcome     <username> [--out DIR]
    ./manage.py lms campus_email enrolment   <username> <course-v1:...> [--out DIR]
    ./manage.py lms campus_email certificate <username> <course-v1:...> [--out DIR]

With ``--out`` the subject/HTML/text are written to files for design review; with ``--send`` the
message goes through ACE exactly as the platform would send it (subject to the once-only
``SentEmail`` record, which ``--resend`` clears first).
"""
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from campus_platform import emails
from campus_platform.models import SentEmail

User = get_user_model()

KINDS = (SentEmail.KIND_WELCOME, SentEmail.KIND_ENROLMENT, SentEmail.KIND_CERTIFICATE)


class Command(BaseCommand):
    help = "Render (default) or send the welcome / enrolment / certificate e-mail."

    def add_arguments(self, parser):
        parser.add_argument("kind", choices=sorted(KINDS))
        parser.add_argument("username")
        parser.add_argument("course_key", nargs="?", default="")
        parser.add_argument("--out", help="directory to write <kind>.subject.txt / .html / .txt into")
        parser.add_argument("--send", action="store_true", help="send through ACE instead of rendering")
        parser.add_argument("--resend", action="store_true", help="clear the once-only record before sending")

    def handle(self, *args, **options):
        kind, username, course_key = options["kind"], options["username"], options["course_key"]
        user = User.objects.filter(username=username).first()
        if user is None:
            raise CommandError(f"no user {username!r}")
        if kind != SentEmail.KIND_WELCOME and not course_key:
            raise CommandError(f"{kind} needs a course key")

        verify_uuid = ""
        if kind == SentEmail.KIND_CERTIFICATE:
            from lms.djangoapps.certificates.models import GeneratedCertificate  # pylint: disable=import-outside-toplevel

            cert = GeneratedCertificate.objects.filter(user=user, course_id=course_key).first()
            if cert is None or not cert.verify_uuid:
                raise CommandError(f"{username} has no certificate for {course_key}")
            verify_uuid = cert.verify_uuid

        if options["send"]:
            if options["resend"]:
                SentEmail.objects.filter(user=user, kind=kind, reference=course_key).delete()
            if kind == SentEmail.KIND_WELCOME:
                sent = emails.send_welcome(user)
            elif kind == SentEmail.KIND_ENROLMENT:
                sent = emails.send_enrolment(user, course_key)
            else:
                sent = emails.send_certificate(user, course_key, verify_uuid)
            self.stdout.write("sent" if sent else "not sent (already sent, no e-mail, or inactive; see log)")
            return

        if kind == SentEmail.KIND_WELCOME:
            context = emails.welcome_context(user)
        elif kind == SentEmail.KIND_ENROLMENT:
            context = emails.enrolment_context(user, course_key)
        else:
            context = emails.certificate_context(user, course_key, verify_uuid)
        subject, html, text = emails.render_preview(user, kind, context)
        if options["out"]:
            out = Path(options["out"])
            out.mkdir(parents=True, exist_ok=True)
            (out / f"{kind}.subject.txt").write_text(subject + "\n", encoding="utf-8")
            (out / f"{kind}.html").write_text(html, encoding="utf-8")
            (out / f"{kind}.txt").write_text(text, encoding="utf-8")
            self.stdout.write(f"{subject}\n→ {out}/{kind}.html")
        else:
            self.stdout.write(f"Subject: {subject}\n\n{text}")
