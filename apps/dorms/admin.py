from django.contrib import admin

from apps.audit.admin_mixins import AuditedAdmin

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


@admin.register(GlobalSettings)
class GlobalSettingsAdmin(admin.ModelAdmin):
    """Read-only here: rules change on /manage/settings/, which asks for the
    password and a reason and records the change in the history."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
