"""Plain-language names for audit action codes, shown in the change history.

Codes are stable strings stored in the database; add new ones here when a
service starts recording them. Words follow docs/GLOSSARY.md: no technical
terms. Unknown codes fall back to a generic "Change".
"""

from django.utils.translation import gettext_lazy as _
from django.utils.translation import pgettext_lazy

LABELS = {
    "booking.cancel_by_staff": _("Booking cancelled by the administration"),
    "ledger.payment": _("Payment recorded"),
    "ledger.correction": _("Balance corrected"),
    "ledger.manual_entry": _("Payment or balance correction"),  # stage 1a events
    "resident.create": _("Resident added"),
    "resident.update": _("Resident details changed"),
    "resident.deactivate": _("Access turned off"),
    "resident.reactivate": _("Access turned back on"),
    "resident.anonymize": _("Personal data erased"),
    "resident.delete": _("Resident deleted"),
    "resident.activation_link": _("Login link created"),
    "resident.pin_reset": _("PIN reset"),
    "user.password_change": _("Password changed"),
    # Changes made by developers in the technical admin (/admin/).
    "admin.add": _("Added by a developer"),
    "admin.change": _("Changed by a developer"),
    "admin.delete": _("Deleted by a developer"),
}


def label(code):
    return LABELS.get(code, pgettext_lazy("change history", "Change"))
