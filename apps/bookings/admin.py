from django.contrib import admin, messages
from django.template.response import TemplateResponse
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy, ngettext

from . import services
from .models import Booking


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    """Read-only. Bookings change only through the booking service, so charges,
    refunds, constraints and the audit log are never bypassed. Staff cancel
    with the actions below; residents book on the site."""

    list_display = ["date", "slot", "machine", "resident", "status", "price_rub"]
    list_filter = ["status", "machine__dormitory", "date"]
    search_fields = ["resident__full_name", "resident__room", "resident__student_code"]
    date_hierarchy = "date"
    list_select_related = ["slot", "machine", "resident"]
    actions = ["cancel_with_refund_rule", "cancel_with_full_refund"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.action(description=gettext_lazy("Cancel with refund rule"))
    def cancel_with_refund_rule(self, request, queryset):
        return self._cancel(request, queryset, full_refund=False)

    @admin.action(description=gettext_lazy("Cancel with full refund"))
    def cancel_with_full_refund(self, request, queryset):
        return self._cancel(request, queryset, full_refund=True)

    def _cancel(self, request, queryset, *, full_refund):
        """First show what will happen and ask for a reason; then cancel each
        booking through the service (each one is its own transaction and audit
        event). Bookings that cannot be cancelled are listed, not forced."""
        bookings = list(
            queryset.select_related("machine__dormitory", "slot", "resident").order_by("starts_at")
        )
        reason = request.POST.get("reason", "").strip()
        if request.POST.get("confirm") and reason:
            cancelled, skipped = 0, []
            for booking in bookings:
                try:
                    services.cancel_booking(
                        booking, actor=request.user, reason=reason, full_refund=full_refund
                    )
                    cancelled += 1
                except services.BookingError as error:
                    skipped.append(f"{booking}: {error.message}")
            if cancelled:
                self.message_user(
                    request,
                    ngettext(
                        "%(count)s booking cancelled.", "%(count)s bookings cancelled.", cancelled
                    )
                    % {"count": cancelled},
                    messages.SUCCESS,
                )
            for line in skipped:
                self.message_user(request, line, messages.WARNING)
            return None  # back to the list

        rows = [
            (
                booking,
                booking.price_rub
                if booking.price_rub and (full_refund or services.refund_due(booking))
                else 0,
            )
            for booking in bookings
        ]
        context = {
            **self.admin_site.each_context(request),
            "title": _("Cancel with full refund") if full_refund else _("Cancel with refund rule"),
            "opts": self.model._meta,
            "rows": rows,
            "action": request.POST.get("action"),
            "reason": reason,
            "reason_missing": bool(request.POST.get("confirm")) and not reason,
            "selected": [booking.pk for booking in bookings],
        }
        return TemplateResponse(request, "admin/bookings/cancel_confirm.html", context)
