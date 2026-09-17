from django.conf import settings
from django.db import models
from opaque_keys.edx.django.models import CourseKeyField

from campus_platform.models import StaffInvitation


class CourseListing(models.Model):
    """
    Marketplace-owned presentation metadata for one Open edX course run, pushed by the integration
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
    institution = models.CharField(max_length=64, help_text="institution code / Open edX org short name")
    institution_name = models.CharField(max_length=160)
    enrolment_policy = models.CharField(
        max_length=16, choices=POLICIES, default=POLICY_ADMISSION,
        help_text="Set by the institution's course admin in Studio (Advanced settings → Other course settings → marketplace)",
    )
    price = models.DecimalField(max_digits=12, decimal_places=2, default=0, help_text="Fixed price for open_paid runs")
    currency = models.CharField(max_length=3, default="NGN")
    institution_logo = models.URLField(blank=True)
    institution_url = models.URLField(blank=True, help_text="Institution profile on the marketplace site")
    programme_title = models.CharField(max_length=200, blank=True, help_text="Parent programme, if the run is part of one")
    programme_url = models.URLField(blank=True, help_text="Programme page on the marketplace site")
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

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="campus_payments")
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


class PartnerRequest(models.Model):
    """
    A prospective institution's request to join the marketplace, submitted from its public site. A marketplace
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
