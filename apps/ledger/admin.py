from django import forms
from django.contrib import admin

from .models import LedgerEntry


class LedgerEntryAdminForm(forms.ModelForm):
    """Admins record credits and adjustments by hand. Booking charges and
    refunds are created automatically by the booking service."""

    kind = forms.ChoiceField(
        choices=[
            (LedgerEntry.Kind.CREDIT, LedgerEntry.Kind.CREDIT.label),
            (LedgerEntry.Kind.ADJUSTMENT, LedgerEntry.Kind.ADJUSTMENT.label),
        ]
    )

    class Meta:
        model = LedgerEntry
        fields = ["resident", "kind", "amount", "note"]


@admin.register(LedgerEntry)
class LedgerEntryAdmin(admin.ModelAdmin):
    form = LedgerEntryAdminForm
    list_display = ["created_at", "resident", "kind", "amount", "booking", "created_by"]
    list_filter = ["kind", "resident__dormitory"]
    search_fields = ["resident__full_name", "resident__room", "resident__student_code", "note"]
    raw_id_fields = ["resident"]

    def save_model(self, request, obj, form, change):
        obj.created_by = request.user
        super().save_model(request, obj, form, change)

    # Append-only: entries can be added and viewed, never changed or deleted.
    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
