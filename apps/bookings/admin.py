from django.contrib import admin

from .models import Booking


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ["date", "slot", "machine", "resident", "status", "price_rub"]
    list_filter = ["status", "machine__dormitory", "date"]
    search_fields = ["resident__full_name", "resident__room", "resident__student_code"]
    date_hierarchy = "date"
    raw_id_fields = ["resident"]
    readonly_fields = ["group_id", "starts_at", "ends_at", "created_at"]
