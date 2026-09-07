from django.conf import settings
from django.db import models
from opaque_keys.edx.django.models import CourseKeyField


class Admission(models.Model):
    """
    An institution's admission decision, recorded by EduLage, that authorises one learner
    to be enrolled in one course run. Enrolment without an active Admission is blocked.
    """

    STATUS_ADMITTED = "admitted"
    STATUS_WITHDRAWN = "withdrawn"
    STATUS_DEFERRED = "deferred"
    STATUS_CHOICES = [
        (STATUS_ADMITTED, "Admitted"),
        (STATUS_WITHDRAWN, "Withdrawn"),
        (STATUS_DEFERRED, "Deferred"),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="edulage_admissions")
    course_key = CourseKeyField(max_length=255, db_index=True)
    application_id = models.CharField(max_length=64, help_text="EduLage application identifier")
    institution = models.CharField(max_length=64, help_text="EduLage institution slug / Open edX org short name")
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_ADMITTED)
    created = models.DateTimeField(auto_now_add=True)
    modified = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("user", "course_key")]

    def __str__(self):
        return f"{self.user.username} → {self.course_key} [{self.status}]"

    @property
    def is_active(self):
        return self.status == self.STATUS_ADMITTED


class ManagedRole(models.Model):
    """An Open edX CourseAccessRole that was granted from an EduLage role claim (so it can be revoked)."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="edulage_roles")
    role = models.CharField(max_length=64)
    org = models.CharField(max_length=64, blank=True)
    course_id = models.CharField(max_length=255, blank=True)

    class Meta:
        unique_together = [("user", "role", "org", "course_id")]
