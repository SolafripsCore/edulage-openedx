from django.contrib import admin

from .models import Admission


@admin.register(Admission)
class AdmissionAdmin(admin.ModelAdmin):
    list_display = ("user", "course_key", "institution", "status", "application_id", "modified")
    list_filter = ("status", "institution")
    search_fields = ("user__username", "user__email", "application_id")
    raw_id_fields = ("user",)
