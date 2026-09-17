from django.contrib import admin

from .models import CourseListing, PartnerRequest, Payment


@admin.register(CourseListing)
class CourseListingAdmin(admin.ModelAdmin):
    list_display = ("course_key", "institution", "institution_name", "classification", "enrolment_policy", "price", "currency", "modified")
    list_filter = ("enrolment_policy", "classification", "institution")
    search_fields = ("course_key", "institution_name", "programme_title")


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    """Read-only ledger; payment state changes only through Paystack verification."""

    list_display = ("reference", "user", "course_key", "institution", "amount", "currency", "status", "enrolled", "paid_at", "created")
    list_filter = ("status", "institution", "currency", "enrolled")
    search_fields = ("reference", "paystack_id", "user__username", "user__email", "email")
    readonly_fields = [f.name for f in Payment._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(PartnerRequest)
class PartnerRequestAdmin(admin.ModelAdmin):
    list_display = ("institution_name", "short_name", "contact_email", "status", "created", "decided")
    list_filter = ("status",)
    search_fields = ("institution_name", "contact_email", "short_name")
