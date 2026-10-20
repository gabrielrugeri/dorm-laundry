from django.contrib import admin

from .actions import label
from .models import AuditEvent


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    """Read-only: the audit log can be viewed here but never changed."""

    list_display = ["created_at", "actor", "action_label", "target_repr", "reason"]
    list_filter = ["action", "dormitory"]
    search_fields = ["target_repr", "reason", "actor__username"]
    date_hierarchy = "created_at"

    @admin.display(description=AuditEvent._meta.get_field("action").verbose_name)
    def action_label(self, event):
        return label(event.action)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
