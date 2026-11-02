"""Machine maintenance and archive: rules, cancellations, refunds, history.
Every name here is fake."""

from datetime import time, timedelta

import pytest
from django.utils import timezone

from apps.accounts import roles
from apps.audit.models import AuditEvent
from apps.bookings import services as booking_services
from apps.bookings.availability import local_today
from apps.bookings.models import Booking
from apps.dorms import machine_state, maintenance
from apps.dorms.models import MachineUnavailability, TimeSlot
from apps.keylog.tests.test_services import make_staff
from apps.ledger.models import LedgerEntry

MAINT = MachineUnavailability.Kind.MAINTENANCE
ARCHIVE = MachineUnavailability.Kind.ARCHIVE


@pytest.fixture
def boss(dormitory):
    return make_staff(dormitory, "boss", role=roles.ADMIN)


@pytest.fixture
def day(dormitory):
    return local_today(dormitory) + timedelta(days=2)


@pytest.fixture
def slot_10(dormitory):
    return TimeSlot.objects.create(dormitory=dormitory, start_time=time(10, 0))


def book(resident, machine, day, slot):
    LedgerEntry.objects.create(resident=resident, kind="credit", amount=50)
    [booking] = booking_services.book_slots(resident, machine, day, [slot])
    return booking


def start(boss, machine, starts_at, ends_at=None, kind=MAINT, refund=True, reason="Broken pump"):
    return maintenance.take_out_of_service(
        actor=boss,
        machine=machine,
        kind=kind,
        starts_at=starts_at,
        ends_at=ends_at,
        reason=reason,
        refund=refund,
    )


def test_maintenance_cancels_and_refunds_affected_bookings(boss, resident, machine, slot, day):
    booking = book(resident, machine, day, slot)
    starts, ends = slot.bounds(day)
    period, cancelled = start(boss, machine, timezone.now(), ends_at=ends)
    booking.refresh_from_db()
    assert cancelled == 1
    assert booking.status == Booking.Status.CANCELLED_BY_ADMIN
    assert "Broken pump" in booking.cancel_reason
    assert LedgerEntry.objects.balance(resident) == 50  # refunded in full
    event = AuditEvent.objects.get(action="machine.maintenance")
    assert event.after["cancelled_bookings"] == 1 and event.reason == "Broken pump"
    assert not machine_state.is_available(machine, day, [slot])


def test_half_open_period_leaves_the_next_slot(boss, resident, machine, slot, slot_10, day):
    later = book(resident, machine, day, slot_10)
    _starts, eight_to_ten_end = slot.bounds(day)
    start(boss, machine, timezone.now(), ends_at=eight_to_ten_end)  # ends at 10:00
    later.refresh_from_db()
    assert later.status == Booking.Status.ACTIVE
    assert machine_state.is_available(machine, day, [slot_10])


def test_without_refund_box_the_usual_rule_applies(boss, resident, machine, slot, day):
    book(resident, machine, day, slot)
    start(boss, machine, timezone.now(), refund=False)
    # Two days ahead the usual rule refunds anyway; what matters is it was not forced.
    assert MachineUnavailability.objects.get().refund is False


@pytest.mark.parametrize(
    "case",
    ["end-before-start", "start-in-past", "archive-with-end", "no-reason"],
)
def test_invalid_periods_are_refused(boss, machine, case):
    now = timezone.now()
    kwargs = {"starts_at": now + timedelta(days=1), "ends_at": now + timedelta(days=2)}
    if case == "end-before-start":
        kwargs["ends_at"] = now + timedelta(hours=1)
    elif case == "start-in-past":
        kwargs["starts_at"] = now - timedelta(hours=3)
    elif case == "archive-with-end":
        kwargs["kind"] = ARCHIVE
    else:
        kwargs["reason"] = " "
    with pytest.raises(maintenance.MaintenanceError):
        start(boss, machine, **kwargs)
    assert not MachineUnavailability.objects.exists()


def test_overlapping_periods_are_refused(boss, machine):
    now = timezone.now()
    start(boss, machine, now + timedelta(days=1), ends_at=now + timedelta(days=3))
    with pytest.raises(maintenance.MaintenanceError):
        start(boss, machine, now + timedelta(days=2), ends_at=now + timedelta(days=4))
    # Back to back is fine (half-open).
    start(boss, machine, now + timedelta(days=3), ends_at=now + timedelta(days=4))


def test_extend_cancels_bookings_in_the_added_time(boss, resident, machine, slot, day):
    booking = book(resident, machine, day, slot)
    now = timezone.now()
    period, _ = start(boss, machine, now, ends_at=now + timedelta(hours=1))
    booking.refresh_from_db()
    assert booking.status == Booking.Status.ACTIVE
    _starts, ends = slot.bounds(day)
    maintenance.extend(actor=boss, period=period, ends_at=ends, reason="Waiting for parts")
    booking.refresh_from_db()
    assert booking.status == Booking.Status.CANCELLED_BY_ADMIN
    with pytest.raises(maintenance.MaintenanceError):
        maintenance.extend(actor=boss, period=period, ends_at=now, reason="x")


def test_end_now_makes_the_machine_bookable(boss, resident, machine, slot, day):
    now = timezone.now()
    period, _ = start(boss, machine, now - timedelta(seconds=30))  # open-ended
    assert not machine_state.is_available(machine, day, [slot])
    maintenance.end_now(actor=boss, period=period)
    assert machine_state.is_available(machine, day, [slot])
    book(resident, machine, day, slot)
    assert AuditEvent.objects.filter(action="machine.maintenance_end").exists()


def test_planned_maintenance_can_be_removed(boss, machine):
    now = timezone.now()
    period, _ = start(boss, machine, now + timedelta(days=5), ends_at=now + timedelta(days=6))
    assert maintenance.end_now(actor=boss, period=period) is None
    assert not MachineUnavailability.objects.exists()
    assert AuditEvent.objects.filter(action="machine.maintenance_cancel").exists()


def test_archive_is_forever(boss, resident, machine, slot, day):
    book(resident, machine, day, slot)
    period, cancelled = start(boss, machine, timezone.now(), kind=ARCHIVE, reason="Replaced")
    assert cancelled == 1
    assert machine.pk in machine_state.archived_ids([machine])
    with pytest.raises(maintenance.MaintenanceError):
        maintenance.end_now(actor=boss, period=period)
    with pytest.raises(maintenance.MaintenanceError):
        start(
            boss,
            machine,
            timezone.now() + timedelta(days=30),
            ends_at=timezone.now() + timedelta(days=31),
        )


def test_in_progress_bookings_are_listed_not_cancelled(resident, machine, dormitory):
    now = timezone.now()
    running = Booking(
        machine=machine,
        resident=resident,
        slot=TimeSlot.objects.create(dormitory=dormitory, start_time=time(0, 0)),
        date=local_today(dormitory),
        price_rub=50,
    )
    running.save()
    Booking.objects.filter(pk=running.pk).update(
        starts_at=now - timedelta(minutes=30), ends_at=now + timedelta(minutes=90)
    )
    future, in_progress = maintenance.affected(machine, now, None, now)
    assert [b.pk for b in in_progress] == [running.pk] and future == []


def test_only_admins_of_the_dormitory(dormitory, other_dormitory, machine):
    now = timezone.now()
    for actor in (
        make_staff(dormitory, "keys", role=roles.MANAGER),
        make_staff(other_dormitory, "stranger", role=roles.ADMIN),
    ):
        with pytest.raises(maintenance.NotAllowed):
            start(actor, machine, now)
