from django import forms
from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from .models import LedgerEntry
from .services import add_manual_entry


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

    def clean_note(self):
        note = self.cleaned_data["note"].strip()
        if not note:
            raise forms.ValidationError(_("A note is required for manual entries."))
        return note


@admin.register(LedgerEntry)
class LedgerEntryAdmin(admin.ModelAdmin):
    form = LedgerEntryAdminForm
    list_display = ["created_at", "resident", "kind", "amount", "booking", "created_by"]
    list_filter = ["kind", "resident__dormitory"]
    search_fields = ["resident__full_name", "resident__room", "resident__student_code", "note"]
    raw_id_fields = ["resident"]

    def save_model(self, request, obj, form, change):
        """Saved through the ledger service, which also writes the audit event."""
        entry = add_manual_entry(
            actor=request.user,
            resident=obj.resident,
            kind=obj.kind,
            amount=obj.amount,
            note=obj.note,
        )
        obj.pk, obj.created_at, obj._state.adding = entry.pk, entry.created_at, False

    # Append-only: entries can be added and viewed, never changed or deleted.
    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
