from django.conf import settings
from django.db import models
from opaque_keys.edx.django.models import CourseKeyField


class Admission(models.Model):
    """
    An institution's admission decision, recorded by EduLage, that authorises one learner
    to be enrolled in one course run. Also carries the application lifecycle (submitted, under
    review) so My learning can show applications before a decision. Enrolment in an
    admission-required run without an active Admission is blocked.

    Keyed by the immutable EduLage user id (OIDC ``sub``). ``user`` is filled when the
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
        ("invited", "Staff invitation sent"),
        ("invite_revoked", "Staff invitation withdrawn"),
        ("invite_accepted", "Staff invitation accepted"),
        ("partner_requested", "Institution partnership requested"),
        ("partner_approved", "Institution partnership approved"),
        ("partner_declined", "Institution partnership declined"),
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

    POLICY_ADMISSION = "admission"
    POLICY_OPEN_FREE = "open_free"
    POLICY_OPEN_PAID = "open_paid"
    POLICIES = [
        (POLICY_ADMISSION, "Admission required"),
        (POLICY_OPEN_FREE, "Open enrolment — free"),
        (POLICY_OPEN_PAID, "Open enrolment — paid"),
    ]

    course_key = CourseKeyField(max_length=255, unique=True)
    institution = models.CharField(max_length=64, help_text="EduLage institution slug / Open edX org short name")
    institution_name = models.CharField(max_length=160)
    enrolment_policy = models.CharField(
        max_length=16, choices=POLICIES, default=POLICY_ADMISSION,
        help_text="Set by the institution's course admin in Studio (Advanced settings → Other course settings → edulage)",
    )
    price = models.DecimalField(max_digits=12, decimal_places=2, default=0, help_text="Fixed price for open_paid runs")
    currency = models.CharField(max_length=3, default="NGN")
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

    @property
    def is_open(self):
        return self.enrolment_policy in (self.POLICY_OPEN_FREE, self.POLICY_OPEN_PAID)

    @property
    def is_paid(self):
        return self.enrolment_policy == self.POLICY_OPEN_PAID

    def as_dict(self):
        return {
            "enrolment_policy": self.enrolment_policy,
            "price": str(self.price) if self.is_paid else "0.00",
            "currency": self.currency,
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


class SentEmail(models.Model):
    """
    One row per EduLage transactional e-mail delivered to a learner, keyed by message kind and
    subject (course run, certificate, or empty for account-level mail). Open edX re-saves
    certificates and enrolments freely, so this is what keeps each notice to a single send.
    """

    KIND_WELCOME = "welcome"
    KIND_ENROLMENT = "enrolment"
    KIND_CERTIFICATE = "certificate"
    KIND_RECEIPT = "receipt"
    KIND_CHOICES = [
        (KIND_WELCOME, "Welcome to EduLage"),
        (KIND_ENROLMENT, "Enrolment confirmed"),
        (KIND_CERTIFICATE, "Credential recorded"),
        (KIND_RECEIPT, "Payment receipt"),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="edulage_emails")
    kind = models.CharField(max_length=16, choices=KIND_CHOICES)
    reference = models.CharField(max_length=255, blank=True, help_text="course run key or certificate id; empty for account mail")
    sent = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("user", "kind", "reference")]

    def __str__(self):
        return f"{self.kind} → {self.user.username} {self.reference}".strip()


class Payment(models.Model):
    """
    One Paystack transaction for one learner and one paid open-enrolment run. Created when
    checkout is initialised (``initialized``), settled only by server-side verification
    (``/transaction/verify`` or a signature-checked webhook) — never by the browser callback
    alone. ``status=success`` is what the enrolment filter accepts; ``enrolled`` records that the
    enrolment has been created so repeated callbacks/webhooks are no-ops.
    Institution-scoped so each institution's records and payouts can be reconciled.
    """

    STATUS_INITIALIZED = "initialized"
    STATUS_SUCCESS = "success"
    STATUS_FAILED = "failed"
    STATUS_ABANDONED = "abandoned"
    STATUS_CHOICES = [
        (STATUS_INITIALIZED, "Initialised"),
        (STATUS_SUCCESS, "Successful"),
        (STATUS_FAILED, "Failed"),
        (STATUS_ABANDONED, "Abandoned"),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="edulage_payments")
    course_key = CourseKeyField(max_length=255, db_index=True)
    institution = models.CharField(max_length=64, db_index=True, help_text="Open edX org short name of the run")
    reference = models.CharField(max_length=64, unique=True, help_text="Our reference, passed to Paystack")
    amount = models.DecimalField(max_digits=12, decimal_places=2, help_text="Major units (e.g. NGN), price at checkout")
    currency = models.CharField(max_length=3, default="NGN")
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_INITIALIZED, db_index=True)
    email = models.EmailField(help_text="Customer e-mail sent to Paystack")
    paystack_id = models.CharField(max_length=32, blank=True, help_text="Paystack transaction id")
    channel = models.CharField(max_length=32, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    gateway_response = models.CharField(max_length=255, blank=True)
    enrolled = models.BooleanField(default=False)
    created = models.DateTimeField(auto_now_add=True)
    modified = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created"]

    def __str__(self):
        return f"{self.reference} {self.user.username} → {self.course_key} {self.amount} {self.currency} [{self.status}]"

    @property
    def amount_minor(self):
        return int(round(self.amount * 100))


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


class PartnerRequest(models.Model):
    """
    A prospective institution's request to join EduLage, submitted from edulage.org. An EduLage
    administrator approves it (creating the organisation and tenant, and inviting the contact
    as the first institution administrator) or declines it.
    """

    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_DECLINED = "declined"
    STATUS_CHOICES = [(STATUS_PENDING, "Pending review"), (STATUS_APPROVED, "Approved"), (STATUS_DECLINED, "Declined")]

    institution_name = models.CharField(max_length=160)
    short_name = models.CharField(max_length=16, blank=True, help_text="Proposed institution code (Open edX org short name)")
    country = models.CharField(max_length=80, blank=True)
    website = models.URLField(blank=True)
    contact_name = models.CharField(max_length=120)
    contact_email = models.EmailField(db_index=True)
    contact_role = models.CharField(max_length=120, blank=True)
    message = models.TextField(blank=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING, db_index=True)
    created = models.DateTimeField(auto_now_add=True)
    decided = models.DateTimeField(null=True, blank=True)
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    note = models.TextField(blank=True, help_text="Reason sent to the contact on decline; internal note on approval")
    invitation = models.ForeignKey(StaffInvitation, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")

    class Meta:
        ordering = ["-created"]

    def __str__(self):
        return f"{self.institution_name} ({self.contact_email}) [{self.status}]"
