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


class TechnicalLimitsForm(forms.ModelForm):
    """Django admin changes only the technical limits (largest receipt file,
    login limits); a reason is required, as on /manage/settings/, and saved
    in the history."""

    reason = forms.CharField(
        label=_("Why are you changing this?"), max_length=500, widget=forms.Textarea
    )

    class Meta:
        model = GlobalSettings
        fields = rules.SUPERUSER_FIELDS

    def clean(self):
        cleaned_data = super().clean()
        for name in rules.SUPERUSER_FIELDS:
            value = cleaned_data.get(name)
            low, high = rules.bounds()[name]
            if value is not None and not low <= value <= high:
                self.add_error(
                    name, _("Between %(low)s and %(high)s.") % {"low": low, "high": high}
                )
        first = cleaned_data.get("login_account_lock_seconds")
        longest = cleaned_data.get("login_account_max_lock_seconds")
        if first and longest and longest < first:
            self.add_error(
                "login_account_max_lock_seconds",
                _("The longest lock cannot be shorter than the first."),
            )
        return cleaned_data


@admin.register(GlobalSettings)
class GlobalSettingsAdmin(admin.ModelAdmin):
    """The money rules are read-only here: dormitory admins change them on
    /manage/settings/ (password, reason, history). The largest receipt file
    and the login limits are technical limits that only superusers change,
    here, through the same service, so they are checked and recorded in the
    history too."""

    form = TechnicalLimitsForm
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
