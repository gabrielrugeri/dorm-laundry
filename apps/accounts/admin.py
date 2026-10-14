from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import Resident, StaffProfile, User

admin.site.register(User, UserAdmin)


@admin.register(Resident)
class ResidentAdmin(admin.ModelAdmin):
    list_display = ["full_name", "room", "student_code", "dormitory", "language"]
    list_filter = ["dormitory"]
    search_fields = ["full_name", "room", "student_code"]
    raw_id_fields = ["user"]


@admin.register(StaffProfile)
class StaffProfileAdmin(admin.ModelAdmin):
    list_display = ["user", "dormitory"]
    list_filter = ["dormitory"]
    raw_id_fields = ["user"]
