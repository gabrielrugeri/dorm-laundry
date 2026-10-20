"""Human-readable names for audit action codes, shown in the audit log.

Codes are stable strings stored in the database; add new ones here when a
service starts recording them. Unknown codes are shown as they are.
"""

from django.utils.translation import gettext_lazy as _

LABELS = {
    "booking.cancel_by_staff": _("Booking cancelled by staff"),
    "ledger.manual_entry": _("Manual ledger entry"),
    "resident.activation_link": _("Activation link created"),
    "resident.pin_reset": _("PIN reset"),
    "user.password_change": _("Password changed"),
    "admin.add": _("Created in Django admin"),
    "admin.change": _("Changed in Django admin"),
    "admin.delete": _("Deleted in Django admin"),
}


def label(code):
    return LABELS.get(code, code)
