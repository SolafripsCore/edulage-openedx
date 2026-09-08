from django.core.management.base import BaseCommand

from edulage_platform.certificates import ensure_html_view_configuration


class Command(BaseCommand):
    help = "Activate the EduLage certificate HTML view configuration (verify URL, wording, links)."

    def handle(self, *args, **options):
        created = ensure_html_view_configuration()
        self.stdout.write("created" if created else "already current")
