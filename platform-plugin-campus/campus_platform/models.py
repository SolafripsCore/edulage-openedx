from django.conf import settings
from django.db import models
from opaque_keys.edx.django.models import CourseKeyField


class Admission(models.Model):
    """
    An institution's admission decision, recorded by the control plane, that authorises one learner
    to be enrolled in one course run. Also carries the application lifecycle (submitted, under
    review) so My learning can show applications before a decision. Enrolment in an
    admission-required run without an active Admission is blocked.

    Keyed by the immutable control-plane user id (OIDC ``sub``). ``user`` is filled when the
    learner has an Open edX account; a *pending* admission (``user`` NULL) is applied at the
    learner's first SSO login, so institutions can admit applicants who have never opened
    the LMS.
    """

    STATUS_SUBMITTED = "submitted"
    STATUS_UNDER_REVIEW = "under_review"
    STATUS_ADMITTED = "admitted"
    STATUS_DECLINED = "declined"
    STATUS_WITHDRAWN = "withdrawn"
    STATUS_DEFERRED = "deferred"
    STATUS_CHOICES = [
        (STATUS_SUBMITTED, "Application submitted"),
        (STATUS_UNDER_REVIEW, "Under review"),
        (STATUS_ADMITTED, "Admitted"),
        (STATUS_DECLINED, "Not admitted"),
        (STATUS_WITHDRAWN, "Withdrawn"),
        (STATUS_DEFERRED, "Deferred"),
    ]
    # Application lifecycle states shown in My learning before a decision is taken.
    OPEN_STATUSES = (STATUS_SUBMITTED, STATUS_UNDER_REVIEW)

    identity_sub = models.CharField(
        max_length=128, null=True, blank=True, db_index=True, help_text="control-plane user id (OIDC sub); NULL if unknown"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE, related_name="campus_admissions"
    )
    course_key = CourseKeyField(max_length=255, db_index=True)
    application_id = models.CharField(max_length=64, help_text="control-plane application identifier")
    institution = models.CharField(max_length=64, help_text="institution code / Open edX org short name")
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_ADMITTED)
    mode = models.CharField(max_length=32, default="honor")
    created = models.DateTimeField(auto_now_add=True)
    modified = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("user", "course_key"), ("identity_sub", "course_key")]

    def __str__(self):
        who = self.user.username if self.user else f"sub:{self.identity_sub} (pending)"
        return f"{who} → {self.course_key} [{self.status}]"

    @property
    def is_active(self):
        return self.status == self.STATUS_ADMITTED

    @property
    def is_pending(self):
        return self.user_id is None


class ManagedRole(models.Model):
    """
    An Open edX CourseAccessRole granted by the control plane (so it can be revoked). ``source`` records
    whether it came from a compact login claim (``token``) or from the audited roles API
    (``api``); each source only reconciles its own grants.
    """

    SOURCE_TOKEN = "token"
    SOURCE_API = "api"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="campus_roles")
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

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="campus_support_scopes")
    institution = models.CharField(max_length=64)
    course_id = models.CharField(max_length=255, blank=True)
    source = models.CharField(max_length=8, default=ManagedRole.SOURCE_TOKEN)

    class Meta:
        unique_together = [("user", "institution", "course_id")]


class IdentityAudit(models.Model):
    """Append-only trail of identity decisions taken by the integration (linking, suspension, roles)."""

    EVENT_CHOICES = [
        ("linked", "Existing account linked to control-plane identity"),
        ("created", "Account created for control-plane identity"),
        ("link_refused", "Account link refused"),
        ("login_refused", "Sign-in refused (identity not active)"),
        ("admission_applied", "Pending admission applied at first login"),
        ("roles_synced", "Roles synchronised"),
        ("suspended", "Account suspended"),
        ("reactivated", "Account reactivated"),
        ("support_lookup", "OEC support looked up a learner"),
        ("invited", "Staff invitation sent"),
        ("invite_revoked", "Staff invitation withdrawn"),
        ("invite_accepted", "Staff invitation accepted"),
        ("partner_requested", "Institution partnership requested"),
        ("partner_approved", "Institution partnership approved"),
        ("partner_declined", "Institution partnership declined"),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    identity_sub = models.CharField(max_length=128, blank=True, db_index=True)
    email = models.CharField(max_length=254, blank=True)
    event = models.CharField(max_length=32, choices=EVENT_CHOICES)
    detail = models.TextField(blank=True)
    actor = models.CharField(max_length=150, blank=True, help_text="service user or 'sso'")
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created"]


class SentEmail(models.Model):
    """
    One row per transactional e-mail delivered to a learner, keyed by message kind and
    subject (course run, certificate, or empty for account-level mail). Open edX re-saves
    certificates and enrolments freely, so this is what keeps each notice to a single send.
    """

    KIND_WELCOME = "welcome"
    KIND_ENROLMENT = "enrolment"
    KIND_CERTIFICATE = "certificate"
    KIND_RECEIPT = "receipt"  # emitted by the marketplace layer
    KIND_CHOICES = [
        (KIND_WELCOME, "Welcome"),
        (KIND_ENROLMENT, "Enrolment confirmed"),
        (KIND_CERTIFICATE, "Credential recorded"),
        (KIND_RECEIPT, "Payment receipt"),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="campus_emails")
    kind = models.CharField(max_length=16, choices=KIND_CHOICES)
    reference = models.CharField(max_length=255, blank=True, help_text="course run key or certificate id; empty for account mail")
    sent = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("user", "kind", "reference")]

    def __str__(self):
        return f"{self.kind} → {self.user.username} {self.reference}".strip()


class StaffInvitation(models.Model):
    """
    An institution administrator's invitation for someone to hold a staff role at their
    institution. Accepted from the e-mailed link by a signed-in account whose e-mail matches;
    acceptance writes the role to the identity provider and mirrors it onto Open edX.
    """

    ORG_ROLES = [
        ("institution_admin", "Institution administrator"),
        ("programme_admin", "Programme administrator"),
        ("course_author", "Course author"),
        ("trainer", "Trainer"),
    ]
    COURSE_ROLES = [
        ("instructor", "Instructor"),
        ("teaching_assistant", "Teaching assistant"),
    ]
    ROLE_CHOICES = ORG_ROLES + COURSE_ROLES
    EXPIRY_DAYS = 14

    token = models.CharField(max_length=64, unique=True)
    email = models.EmailField(db_index=True)
    institution = models.CharField(max_length=64, db_index=True, help_text="Open edX org short name")
    role = models.CharField(max_length=32, choices=ROLE_CHOICES)
    course_id = models.CharField(max_length=255, blank=True, help_text="Course run for instructor / TA roles")
    invited_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    created = models.DateTimeField(auto_now_add=True)
    accepted = models.DateTimeField(null=True, blank=True)
    accepted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    revoked = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created"]

    def __str__(self):
        return f"{self.email} → {self.claim} [{self.state}]"

    @property
    def claim(self):
        return f"{self.role}:{self.course_id or self.institution}"

    @property
    def role_label(self):
        return dict(self.ROLE_CHOICES).get(self.role, self.role)

    @property
    def expires(self):
        from datetime import timedelta  # pylint: disable=import-outside-toplevel

        return self.created + timedelta(days=self.EXPIRY_DAYS)

    @property
    def state(self):
        from django.utils import timezone  # pylint: disable=import-outside-toplevel

        if self.accepted:
            return "accepted"
        if self.revoked:
            return "revoked"
        if timezone.now() > self.expires:
            return "expired"
        return "pending"


class OutboxEvent(models.Model):
    """
    Open edX → control-plane event, written in the same transaction as the fact it reports and
    delivered asynchronously (``events.deliver``). Each row carries a stable UUID, a monotonic
    sequence and a schema version so the receiver can de-duplicate, order and evolve.
    """

    STATUS_PENDING = "pending"
    STATUS_DELIVERED = "delivered"
    STATUS_FAILED = "failed"  # retries exhausted → dead-letter; replay via management command / API
    STATUS_CHOICES = [(STATUS_PENDING, "Pending"), (STATUS_DELIVERED, "Delivered"), (STATUS_FAILED, "Failed")]
    MAX_ATTEMPTS = 8

    uuid = models.UUIDField(unique=True, editable=False)
    sequence = models.BigAutoField(primary_key=True)
    event_type = models.CharField(max_length=80, db_index=True)
    version = models.PositiveSmallIntegerField(default=1)
    institution = models.CharField(max_length=64, blank=True, db_index=True)
    course_key = CourseKeyField(max_length=255, blank=True, null=True)
    identity_sub = models.CharField(max_length=128, blank=True, db_index=True)
    payload = models.JSONField(default=dict)
    occurred = models.DateTimeField()
    created = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=STATUS_PENDING, db_index=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    next_attempt = models.DateTimeField(null=True, blank=True, db_index=True)
    delivered = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)

    class Meta:
        ordering = ["sequence"]

    def __str__(self):
        return f"{self.event_type} #{self.sequence} ({self.status})"
