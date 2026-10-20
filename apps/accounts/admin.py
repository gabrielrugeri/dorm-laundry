from django.conf import settings
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.db import transaction
from django.template.response import TemplateResponse
from django.utils.translation import gettext_lazy as _

from apps.audit.admin_mixins import AuditedAdmin
from apps.audit.services import record

from .activation import activation_url
from .models import Resident, StaffProfile, User


@admin.register(User)
class AuditedUserAdmin(AuditedAdmin, UserAdmin):
    def user_change_password(self, request, id, form_url=""):
        """Record that a password was changed; never what it was changed to."""
        response = super().user_change_password(request, id, form_url)
        if request.method == "POST" and response.status_code == 302:
            user = self.get_object(request, id)
            record(actor=request.user, action="user.password_change", target=user)
        return response


@admin.register(Resident)
class ResidentAdmin(AuditedAdmin, admin.ModelAdmin):
    list_display = ["full_name", "room", "student_code", "dormitory", "language", "has_pin"]
    list_filter = ["dormitory"]
    search_fields = ["full_name", "room", "student_code"]
    raw_id_fields = ["user"]
    list_select_related = ["user", "dormitory"]
    actions = ["create_activation_links", "reset_pins"]

    @admin.display(boolean=True, description=_("PIN set"))
    def has_pin(self, resident):
        return resident.user.has_usable_password()

    @admin.action(description=_("Create activation links"))
    def create_activation_links(self, request, queryset):
        for resident in queryset:
            record(actor=request.user, action="resident.activation_link", target=resident)
        return self._show_links(request, queryset, _("Activation links"))

    @admin.action(description=_("Reset PIN and create activation links"))
    def reset_pins(self, request, queryset):
        """The old PIN stops working at once and open sessions are logged out."""
        with transaction.atomic():
            for resident in queryset.select_related("user"):
                resident.user.set_unusable_password()
                resident.user.save(update_fields=["password"])
                record(actor=request.user, action="resident.pin_reset", target=resident)
        return self._show_links(request, queryset, _("PINs reset"))

    def _show_links(self, request, queryset, title):
        links = [
            (resident, activation_url(request, resident.user))
            for resident in queryset.select_related("user")
        ]
        context = {
            **self.admin_site.each_context(request),
            "title": title,
            "links": links,
            "valid_days": settings.PASSWORD_RESET_TIMEOUT // (60 * 60 * 24),
            "opts": self.model._meta,
        }
        return TemplateResponse(request, "admin/accounts/activation_links.html", context)


@admin.register(StaffProfile)
class StaffProfileAdmin(AuditedAdmin, admin.ModelAdmin):
    list_display = ["user", "dormitory"]
    list_filter = ["dormitory"]
    raw_id_fields = ["user"]
