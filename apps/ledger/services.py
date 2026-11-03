"""Manual money movements recorded by staff (credits after a payment,
adjustments to correct mistakes). Booking charges and refunds are made by the
booking service; receipts (stage 4) will make their own credits."""

from django.db import transaction

from apps.audit.services import record, snapshot

from .models import LedgerEntry


def add_manual_entry(*, actor, resident, kind, amount, note=""):
    """Add a payment (credit, either sign) or a correction (adjustment), and
    audit it. Corrections need a note; for payments it is optional."""
    if kind not in (LedgerEntry.Kind.CREDIT, LedgerEntry.Kind.ADJUSTMENT):
        raise ValueError("Only credits and adjustments are entered by hand.")
    note = note.strip()
    if kind == LedgerEntry.Kind.ADJUSTMENT and not note:
        raise ValueError("A note is required for a correction.")
    with transaction.atomic():
        entry = LedgerEntry.objects.create(
            resident=resident, kind=kind, amount=amount, note=note, created_by=actor
        )
        record(
            actor=actor,
            action="ledger.payment" if kind == LedgerEntry.Kind.CREDIT else "ledger.correction",
            target=entry,
            after=snapshot(entry),
            reason=note,
            dormitory=resident.dormitory,
        )
    return entry


def set_opening_balance(*, actor, resident, amount):
    """The balance a resident had before the app (from the residents import):
    positive for money already paid, negative for an old debt. At most once
    per resident (the database refuses a second one). The credit limit
    applies from then on, like after any other entry."""
    if not amount:
        raise ValueError("An opening balance is never 0.")
    with transaction.atomic():
        entry = LedgerEntry.objects.create(
            resident=resident, kind=LedgerEntry.Kind.OPENING, amount=amount, created_by=actor
        )
        record(
            actor=actor,
            action="ledger.opening",
            target=entry,
            after=snapshot(entry),
            dormitory=resident.dormitory,
        )
    return entry
