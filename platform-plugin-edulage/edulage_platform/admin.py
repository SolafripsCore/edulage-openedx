from django.contrib import admin

from .models import Admission, CourseListing, IdentityAudit, ManagedRole, Payment, SupportScope


@admin.register(Admission)
class AdmissionAdmin(admin.ModelAdmin):
    list_display = ("edulage_sub", "user", "course_key", "institution", "status", "application_id", "modified")
    list_filter = ("status", "institution")
    search_fields = ("edulage_sub", "user__username", "user__email", "application_id")
    raw_id_fields = ("user",)


@admin.register(ManagedRole)
class ManagedRoleAdmin(admin.ModelAdmin):
    list_display = ("user", "role", "org", "course_id", "source")
    list_filter = ("source", "role", "org")
    search_fields = ("user__username",)
    raw_id_fields = ("user",)


@admin.register(SupportScope)
class SupportScopeAdmin(admin.ModelAdmin):
    list_display = ("user", "institution", "course_id", "source")
    list_filter = ("institution",)
    raw_id_fields = ("user",)


@admin.register(IdentityAudit)
class IdentityAuditAdmin(admin.ModelAdmin):
    list_display = ("created", "event", "user", "edulage_sub", "email", "actor", "detail")
    list_filter = ("event", "actor")
    search_fields = ("edulage_sub", "email", "user__username", "detail")
    readonly_fields = [f.name for f in IdentityAudit._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


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
