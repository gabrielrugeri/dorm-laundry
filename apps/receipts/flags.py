"""Hints for the admin reviewing receipts: what deserves a closer look.

Flags never block or change anything; receipts are trusted by default and a
flag only says "check this one first". Each flag is a short code with a
plain-language label (docs/GLOSSARY.md).
"""

from datetime import timedelta

from django.db.models import Sum
from django.utils.translation import gettext_lazy as _

from apps.dorms import rules
from apps.ledger.models import LedgerEntry

from .models import Receipt

LABELS = {
    "repeat": _("Same amount sent again within 2 days"),
    "large": _("Large amount"),
    "spent_quickly": _("Spent on bookings right after"),
    "negative_balance": _("Resident is in debt now"),
    "earlier_voids": _("Resident had receipts voided before"),
    "near_cap": _("Close to the 30-day limit"),
}

REPEAT_WINDOW = timedelta(days=2)
SPENT_WINDOW = timedelta(hours=2)
NEAR = 0.8  # "large" and "close to the limit": 80% or more


def flags_for(receipt, current=None):
    """[(code, label), ...] for one receipt."""
    current = current or rules.current()
    resident = receipt.resident
    found = []

    others = Receipt.objects.filter(resident=resident).exclude(pk=receipt.pk)
    if others.filter(
        amount=receipt.amount,
        uploaded_at__gte=receipt.uploaded_at - REPEAT_WINDOW,
        uploaded_at__lte=receipt.uploaded_at + REPEAT_WINDOW,
    ).exists():
        found.append("repeat")

    if receipt.amount >= NEAR * current.max_receipt_amount:
        found.append("large")

    spent = LedgerEntry.objects.filter(
        resident=resident,
        kind=LedgerEntry.Kind.BOOKING,
        created_at__gte=receipt.uploaded_at,
        created_at__lte=receipt.uploaded_at + SPENT_WINDOW,
    ).aggregate(total=Sum("amount"))["total"]
    if spent and -spent >= receipt.amount / 2:
        found.append("spent_quickly")

    if LedgerEntry.objects.balance(resident) < 0:
        found.append("negative_balance")

    if others.filter(status=Receipt.Status.VOIDED).exists():
        found.append("earlier_voids")

    window = Receipt.objects.filter(
        resident=resident,
        status=Receipt.Status.CREDITED,
        uploaded_at__gt=receipt.uploaded_at - timedelta(days=30),
        uploaded_at__lte=receipt.uploaded_at,
    ).aggregate(total=Sum("amount"))["total"]
    if window and window >= NEAR * current.max_credit_per_30_days:
        found.append("near_cap")

    return [(code, LABELS[code]) for code in found]
