from django.contrib import admin

from .models import Receipt


@admin.register(Receipt)
class ReceiptAdmin(admin.ModelAdmin):
    """Read-only: receipts are created by residents through the receipt
    service and voided by admins on /manage/ (Stage 5)."""

    list_display = ["uploaded_at", "resident", "amount", "status"]
    list_filter = ["status", "resident__dormitory"]
    raw_id_fields = ["resident"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
