"""Celery tasks (Open edX worker): outbox delivery, scheduled via ``events.schedule_delivery``."""
from celery import shared_task

from . import events


@shared_task(name="campus_platform.deliver_pending", ignore_result=True)
def deliver_pending():
    return events.deliver_pending_now()
