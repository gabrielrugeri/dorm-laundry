import pytest
from django.db import IntegrityError, transaction

from apps.ledger.models import LedgerEntry

Kind = LedgerEntry.Kind


def entry(resident, kind, amount, booking=None):
    return LedgerEntry.objects.create(resident=resident, kind=kind, amount=amount, booking=booking)


def test_balance_is_sum_of_entries(resident, make_booking):
    assert LedgerEntry.objects.balance(resident) == 0
    entry(resident, Kind.CREDIT, 200)
    booking = make_booking()
    entry(resident, Kind.BOOKING, -50, booking)
    entry(resident, Kind.REFUND, 50, booking)
    entry(resident, Kind.ADJUSTMENT, -30)
    assert LedgerEntry.objects.balance(resident) == 170


def test_balance_is_per_resident(resident, other_resident):
    entry(resident, Kind.CREDIT, 100)
    assert LedgerEntry.objects.balance(other_resident) == 0


@pytest.mark.parametrize(
    ("kind", "amount", "needs_booking"),
    [
        (Kind.CREDIT, 0, False),
        (Kind.BOOKING, 50, True),
        (Kind.REFUND, -50, True),
        (Kind.ADJUSTMENT, 0, False),
    ],
)
def test_wrong_sign_rejected(resident, make_booking, kind, amount, needs_booking):
    booking = make_booking() if needs_booking else None
    with pytest.raises(IntegrityError), transaction.atomic():
        entry(resident, kind, amount, booking)


def test_booking_charge_requires_booking(resident):
    with pytest.raises(IntegrityError), transaction.atomic():
        entry(resident, Kind.BOOKING, -50)


def test_credit_cannot_reference_booking(resident, make_booking):
    with pytest.raises(IntegrityError), transaction.atomic():
        entry(resident, Kind.CREDIT, 50, make_booking())


def test_booking_cannot_be_refunded_twice(resident, make_booking):
    booking = make_booking()
    entry(resident, Kind.BOOKING, -50, booking)
    entry(resident, Kind.REFUND, 50, booking)
    with pytest.raises(IntegrityError), transaction.atomic():
        entry(resident, Kind.REFUND, 50, booking)


def test_booking_cannot_be_charged_twice(resident, make_booking):
    booking = make_booking()
    entry(resident, Kind.BOOKING, -50, booking)
    with pytest.raises(IntegrityError), transaction.atomic():
        entry(resident, Kind.BOOKING, -50, booking)


def test_entries_cannot_be_edited_or_deleted(resident):
    credit = entry(resident, Kind.CREDIT, 100)
    credit.amount = 1000
    with pytest.raises(ValueError):
        credit.save()
    with pytest.raises(ValueError):
        credit.delete()
    assert LedgerEntry.objects.balance(resident) == 100
