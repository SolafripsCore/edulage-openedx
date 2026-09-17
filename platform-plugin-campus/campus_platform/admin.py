from django.contrib import admin

from .models import Admission, IdentityAudit, ManagedRole, OutboxEvent, SupportScope


@admin.register(Admission)
class AdmissionAdmin(admin.ModelAdmin):
    list_display = ("identity_sub", "user", "course_key", "institution", "status", "application_id", "modified")
    list_filter = ("status", "institution")
    search_fields = ("identity_sub", "user__username", "user__email", "application_id")
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
    list_display = ("created", "event", "user", "identity_sub", "email", "actor", "detail")
    list_filter = ("event", "actor")
    search_fields = ("identity_sub", "email", "user__username", "detail")
    readonly_fields = [f.name for f in IdentityAudit._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(OutboxEvent)
class OutboxEventAdmin(admin.ModelAdmin):
    list_display = ("sequence", "event_type", "institution", "course_key", "status", "attempts", "occurred", "delivered")
    list_filter = ("status", "event_type")
    search_fields = ("uuid", "institution", "identity_sub", "course_key")
    readonly_fields = [f.name for f in OutboxEvent._meta.fields]
