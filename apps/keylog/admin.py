from django.contrib import admin

from apps.audit.admin_mixins import AuditedAdmin

from .models import KeyLog


@admin.register(KeyLog)
class KeyLogAdmin(AuditedAdmin, admin.ModelAdmin):
    list_display = ["booking", "taken_at", "returned_at", "recorded_by"]
    list_filter = ["booking__machine__dormitory"]
    raw_id_fields = ["booking"]
    readonly_fields = ["recorded_by"]

    def save_model(self, request, obj, form, change):
        obj.recorded_by = request.user
        super().save_model(request, obj, form, change)
