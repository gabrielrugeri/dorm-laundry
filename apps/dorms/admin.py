from django.contrib import admin

from .models import Dormitory, Machine, TimeSlot


class TimeSlotInline(admin.TabularInline):
    model = TimeSlot
    extra = 0


class MachineInline(admin.TabularInline):
    model = Machine
    extra = 0


@admin.register(Dormitory)
class DormitoryAdmin(admin.ModelAdmin):
    list_display = ["name", "slug", "timezone", "price_per_slot"]
    prepopulated_fields = {"slug": ["name"]}
    inlines = [TimeSlotInline, MachineInline]
