from django import forms
from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from apps.audit.admin_mixins import AuditedAdmin

from . import rules
from .models import Dormitory, GlobalSettings, Machine, TimeSlot


class TimeSlotInline(admin.TabularInline):
    model = TimeSlot
    extra = 0


class MachineInline(admin.TabularInline):
    model = Machine
    extra = 0


@admin.register(Dormitory)
class DormitoryAdmin(AuditedAdmin, admin.ModelAdmin):
    list_display = ["name", "code", "slug", "timezone", "price_per_slot"]
    prepopulated_fields = {"slug": ["name"]}
    inlines = [TimeSlotInline, MachineInline]


class UploadLimitForm(forms.ModelForm):
    """Django admin changes only the largest receipt file; a reason is
    required, as on /manage/settings/, and saved in the history."""

    reason = forms.CharField(
        label=_("Why are you changing this?"), max_length=500, widget=forms.Textarea
    )

    class Meta:
        model = GlobalSettings
        fields = rules.SUPERUSER_FIELDS

    def clean_max_upload_mb(self):
        value = self.cleaned_data["max_upload_mb"]
        low, high = rules.bounds()["max_upload_mb"]
        if not low <= value <= high:
            raise forms.ValidationError(
                _("Between %(low)s and %(high)s MB (the server's own limit).")
                % {"low": low, "high": high}
            )
        return value


@admin.register(GlobalSettings)
class GlobalSettingsAdmin(admin.ModelAdmin):
    """The money rules are read-only here: dormitory admins change them on
    /manage/settings/ (password, reason, history). The largest receipt file
    is a technical limit that only superusers change, here, through the same
    service, so it is checked and recorded in the history too."""

    form = UploadLimitForm
    fields = (*rules.FIELDS, *rules.SUPERUSER_FIELDS, "reason", "updated_at")
    readonly_fields = (*rules.FIELDS, "updated_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        rules.change_settings(
            actor=request.user,
            values={name: form.cleaned_data[name] for name in rules.SUPERUSER_FIELDS},
            reason=form.cleaned_data["reason"],
        )
