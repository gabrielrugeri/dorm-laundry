from django.contrib import admin

from .models import PaymentDetails


@admin.register(PaymentDetails)
class PaymentDetailsAdmin(admin.ModelAdmin):
    """Read-only here: changed on /manage/settings/payments/, which asks for
    the password and a reason and records the change."""

    list_display = ["dormitory", "recipient", "bank", "updated_at"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
