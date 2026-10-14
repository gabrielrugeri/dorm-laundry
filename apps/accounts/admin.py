from django.conf import settings
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.template.response import TemplateResponse
from django.utils.translation import gettext_lazy as _

from .activation import activation_url
from .models import Resident, StaffProfile, User

admin.site.register(User, UserAdmin)


@admin.register(Resident)
class ResidentAdmin(admin.ModelAdmin):
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
        return self._show_links(request, queryset, _("Activation links"))

    @admin.action(description=_("Reset PIN and create activation links"))
    def reset_pins(self, request, queryset):
        """The old PIN stops working at once and open sessions are logged out."""
        for resident in queryset.select_related("user"):
            resident.user.set_unusable_password()
            resident.user.save(update_fields=["password"])
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
class StaffProfileAdmin(admin.ModelAdmin):
    list_display = ["user", "dormitory"]
    list_filter = ["dormitory"]
    raw_id_fields = ["user"]
