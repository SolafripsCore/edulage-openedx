"""Outbox operations: deliver due events, list dead letters, replay by id."""
from django.core.management.base import BaseCommand

from campus_platform import events
from campus_platform.models import OutboxEvent


class Command(BaseCommand):
    help = "Deliver pending control-plane events, show failed ones, or replay them."

    def add_arguments(self, parser):
        parser.add_argument("action", choices=["deliver", "failed", "replay"])
        parser.add_argument("ids", nargs="*", help="event UUIDs for replay")

    def handle(self, *args, **options):
        if options["action"] == "deliver":
            self.stdout.write(f"delivered {events.deliver_pending_now()}")
        elif options["action"] == "failed":
            for e in OutboxEvent.objects.filter(status=OutboxEvent.STATUS_FAILED):
                self.stdout.write(f"{e.uuid} {e.sequence} {e.event_type} {e.institution} {e.last_error[:120]}")
        else:
            self.stdout.write(f"re-queued {events.replay(options['ids'])}")
