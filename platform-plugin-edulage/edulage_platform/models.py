from django.conf import settings
from django.db import models
from opaque_keys.edx.django.models import CourseKeyField


class Admission(models.Model):
    """
    An institution's admission decision, recorded by EduLage, that authorises one learner
    to be enrolled in one course run. Enrolment without an active Admission is blocked.

    Keyed by the immutable EduLage user id (OIDC ``sub``). ``user`` is filled when the
    learner has an Open edX account; a *pending* admission (``user`` NULL) is applied at the
    learner's first SSO login, so institutions can admit applicants who have never opened
    the LMS.
    """

    STATUS_ADMITTED = "admitted"
    STATUS_WITHDRAWN = "withdrawn"
    STATUS_DEFERRED = "deferred"
    STATUS_CHOICES = [
        (STATUS_ADMITTED, "Admitted"),
        (STATUS_WITHDRAWN, "Withdrawn"),
        (STATUS_DEFERRED, "Deferred"),
    ]

    edulage_sub = models.CharField(
        max_length=128, null=True, blank=True, db_index=True, help_text="EduLage user id (OIDC sub); NULL if unknown"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE, related_name="edulage_admissions"
    )
    course_key = CourseKeyField(max_length=255, db_index=True)
    application_id = models.CharField(max_length=64, help_text="EduLage application identifier")
    institution = models.CharField(max_length=64, help_text="EduLage institution slug / Open edX org short name")
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_ADMITTED)
    mode = models.CharField(max_length=32, default="honor")
    created = models.DateTimeField(auto_now_add=True)
    modified = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("user", "course_key"), ("edulage_sub", "course_key")]

    def __str__(self):
        who = self.user.username if self.user else f"sub:{self.edulage_sub} (pending)"
        return f"{who} → {self.course_key} [{self.status}]"

    @property
    def is_active(self):
        return self.status == self.STATUS_ADMITTED

    @property
    def is_pending(self):
        return self.user_id is None


class ManagedRole(models.Model):
    """
    An Open edX CourseAccessRole granted by EduLage (so it can be revoked). ``source`` records
    whether it came from a compact login claim (``token``) or from the audited roles API
    (``api``); each source only reconciles its own grants.
    """

    SOURCE_TOKEN = "token"
    SOURCE_API = "api"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="edulage_roles")
    role = models.CharField(max_length=64)
    org = models.CharField(max_length=64, blank=True)
    course_id = models.CharField(max_length=255, blank=True)
    source = models.CharField(max_length=8, default=SOURCE_TOKEN)

    class Meta:
        unique_together = [("user", "role", "org", "course_id")]


class SupportScope(models.Model):
    """
    OEC support officer entitlement: read-only learner-support access limited to one
    institution (optionally one course run). Replaces Open edX's platform-wide
    SupportStaffRole for OEC staff.
    """

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="edulage_support_scopes")
    institution = models.CharField(max_length=64)
    course_id = models.CharField(max_length=255, blank=True)
    source = models.CharField(max_length=8, default=ManagedRole.SOURCE_TOKEN)

    class Meta:
        unique_together = [("user", "institution", "course_id")]


class IdentityAudit(models.Model):
    """Append-only trail of identity decisions taken by the integration (linking, suspension, roles)."""

    EVENT_CHOICES = [
        ("linked", "Existing account linked to EduLage identity"),
        ("created", "Account created for EduLage identity"),
        ("link_refused", "Account link refused"),
        ("login_refused", "Sign-in refused (identity not active)"),
        ("admission_applied", "Pending admission applied at first login"),
        ("roles_synced", "Roles synchronised"),
        ("suspended", "Account suspended"),
        ("reactivated", "Account reactivated"),
        ("support_lookup", "OEC support looked up a learner"),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    edulage_sub = models.CharField(max_length=128, blank=True, db_index=True)
    email = models.CharField(max_length=254, blank=True)
    event = models.CharField(max_length=32, choices=EVENT_CHOICES)
    detail = models.TextField(blank=True)
    actor = models.CharField(max_length=150, blank=True, help_text="service user or 'sso'")
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created"]


class CourseListing(models.Model):
    """
    EduLage-owned presentation metadata for one Open edX course run, pushed by the integration
    layer from the authoritative programme catalogue. The learner dashboard uses it to show the
    institution, classification and programme instead of Open edX's bare "org • course number".
    Rows are optional: runs without one fall back to the Open edX organisation.
    """

    CLASSIFICATIONS = [
        ("degree", "Degree programme"),
        ("postgraduate", "Postgraduate programme"),
        ("professional", "Professional programme"),
        ("certificate", "Certificate course"),
        ("short", "Short course"),
        ("executive", "Executive education"),
        ("open", "Open course"),
        ("cpd", "Continuing professional development"),
    ]

    course_key = CourseKeyField(max_length=255, unique=True)
    institution = models.CharField(max_length=64, help_text="EduLage institution slug / Open edX org short name")
    institution_name = models.CharField(max_length=160)
    institution_logo = models.URLField(blank=True)
    institution_url = models.URLField(blank=True, help_text="Institution profile on edulage.org")
    programme_title = models.CharField(max_length=200, blank=True, help_text="Parent programme, if the run is part of one")
    programme_url = models.URLField(blank=True, help_text="Programme page on edulage.org")
    classification = models.CharField(max_length=16, choices=CLASSIFICATIONS, default="short")
    credential = models.CharField(max_length=64, blank=True, help_text="e.g. MSc, PGD, Certificate of completion")
    delivery_mode = models.CharField(max_length=32, blank=True, help_text="e.g. Fully online, Online + OEC exams")
    modified = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.course_key} ({self.institution})"

    def as_dict(self):
        return {
            "institution": self.institution,
            "institution_name": self.institution_name,
            "institution_logo": self.institution_logo,
            "institution_url": self.institution_url,
            "programme_title": self.programme_title,
            "programme_url": self.programme_url,
            "classification": self.classification,
            "classification_label": self.get_classification_display(),
            "credential": self.credential,
            "delivery_mode": self.delivery_mode,
        }
