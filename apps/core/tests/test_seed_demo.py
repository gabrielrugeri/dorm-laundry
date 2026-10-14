from django.core.management import call_command

from apps.accounts import roles
from apps.accounts.models import Resident, User
from apps.bookings.models import Booking
from apps.dorms.models import Machine, TimeSlot
from apps.ledger.models import LedgerEntry


def test_seed_demo_creates_data_and_is_idempotent(db):
    call_command("seed_demo")
    counts = (
        Resident.objects.count(),
        Machine.objects.count(),
        TimeSlot.objects.count(),
        Booking.objects.count(),
        LedgerEntry.objects.count(),
    )
    assert counts[:3] == (20, 6, 7)

    call_command("seed_demo")
    assert counts == (
        Resident.objects.count(),
        Machine.objects.count(),
        TimeSlot.objects.count(),
        Booking.objects.count(),
        LedgerEntry.objects.count(),
    )


def test_seed_demo_ledger_is_consistent(db):
    call_command("seed_demo")
    for resident in Resident.objects.all():
        assert LedgerEntry.objects.balance(resident) >= 0
    for booking in Booking.objects.all():
        assert booking.ledger_entries.get().amount == -booking.price_rub


def test_seed_demo_roles(db):
    call_command("seed_demo")
    assert roles.has_role(User.objects.get(username="manager"), roles.MANAGER)
    assert roles.has_role(User.objects.get(username="admin"), roles.ADMIN)
    assert roles.has_role(Resident.objects.first().user, roles.RESIDENT)
