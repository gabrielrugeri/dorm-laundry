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
        assert booking.ledger_entries.get(kind="booking").amount == -booking.price_rub


def test_seed_demo_roles(db):
    call_command("seed_demo")
    assert roles.has_role(User.objects.get(username="manager"), roles.MANAGER)
    assert roles.has_role(User.objects.get(username="admin"), roles.ADMIN)
    assert roles.has_role(Resident.objects.first().user, roles.RESIDENT)


def test_seed_demo_slots_run_from_10_to_midnight(db):
    from datetime import time

    from apps.dorms.models import Dormitory

    old = Dormitory.objects.create(name="Demo", slug="demo")
    TimeSlot.objects.create(dormitory=old, start_time=time(8, 0))
    call_command("seed_demo")
    active = TimeSlot.objects.filter(active=True).order_by("start_time")
    assert [s.start_time.hour for s in active] == [10, 12, 14, 16, 18, 20, 22]
    assert str(active.last()) == "22:00–00:00"
    assert not TimeSlot.objects.get(start_time=time(8, 0)).active


def test_seed_demo_has_an_audited_admin_cancellation(db):
    from apps.audit.models import AuditEvent

    call_command("seed_demo")
    cancelled = Booking.objects.get(status=Booking.Status.CANCELLED_BY_ADMIN)
    assert cancelled.cancel_reason
    assert cancelled.ledger_entries.filter(kind="refund").exists()
    assert (
        AuditEvent.objects.filter(
            action="booking.cancel_by_staff", target_id=str(cancelled.pk)
        ).count()
        == 1
    )
