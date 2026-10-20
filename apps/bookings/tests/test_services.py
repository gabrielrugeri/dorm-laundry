"""Tests for the booking service. Every name and code here is fake.

Times are passed with `now=` so the tests do not depend on the real clock.
Slots are local Moscow time (UTC+3): 08:00 local is 05:00 UTC.
"""

from datetime import UTC, date, datetime, time, timedelta

import pytest
from django.contrib.auth.models import Group
from django.utils import translation

from apps.accounts import roles
from apps.accounts.models import StaffProfile, User
from apps.audit.models import AuditEvent
from apps.bookings import services
from apps.bookings.models import Booking
from apps.dorms.models import Machine, TimeSlot
from apps.ledger.models import LedgerEntry

DAY = date(2026, 10, 20)
# The day before DAY, at noon Moscow time.
NOW = datetime(2026, 10, 19, 9, 0, tzinfo=UTC)


@pytest.fixture
def slot_10(dormitory):
    return TimeSlot.objects.create(dormitory=dormitory, start_time=time(10, 0))


@pytest.fixture
def slot_12(dormitory):
    return TimeSlot.objects.create(dormitory=dormitory, start_time=time(12, 0))


# --- Errors --------------------------------------------------------------------


def test_error_message_is_translated():
    error = services.InsufficientBalance()
    with translation.override("ru"):
        assert str(error.message) == "Недостаточно средств на балансе для этого бронирования."
    with translation.override("en"):
        assert str(error.message) == "Your balance is too low for this booking."


def test_error_message_can_be_overridden():
    assert services.BookingError("custom").message == "custom"


# --- Checks --------------------------------------------------------------------


def test_same_dormitory_check(dormitory, other_dormitory, machine, slot):
    services._check_same_dormitory(dormitory, machine, [slot])
    foreign_machine = Machine.objects.create(dormitory=other_dormitory, number=9)
    with pytest.raises(services.WrongDormitory):
        services._check_same_dormitory(dormitory, foreign_machine, [slot])
    foreign_slot = TimeSlot.objects.create(dormitory=other_dormitory, start_time=time(8, 0))
    with pytest.raises(services.WrongDormitory):
        services._check_same_dormitory(dormitory, machine, [slot, foreign_slot])


def test_bookable_check(machine, slot):
    services._check_bookable(machine, [slot])
    slot.active = False
    with pytest.raises(services.SlotUnavailable):
        services._check_bookable(machine, [slot])
    machine.active = False
    with pytest.raises(services.MachineUnavailable):
        services._check_bookable(machine, [slot])


def test_consecutive_check_accepts_neighbours(dormitory, slot, slot_10, slot_12):
    services._check_consecutive(dormitory, [slot])
    services._check_consecutive(dormitory, [slot, slot_10])
    services._check_consecutive(dormitory, [slot, slot_10, slot_12])


def test_consecutive_check_rejects_skipped_slot(dormitory, slot, slot_10, slot_12):
    with pytest.raises(services.SlotsNotConsecutive):
        services._check_consecutive(dormitory, [slot, slot_12])


def test_consecutive_check_rejects_time_gap(dormitory, slot, slot_12):
    # 08:00–10:00 and 12:00–14:00 are neighbours in the list, but not back to back.
    with pytest.raises(services.SlotsNotConsecutive):
        services._check_consecutive(dormitory, [slot, slot_12])


def test_consecutive_check_rejects_duplicates(dormitory, slot, slot_10):
    with pytest.raises(services.SlotsNotConsecutive):
        services._check_consecutive(dormitory, [slot, slot])


def test_booking_window(dormitory, slot):
    # Tomorrow is fine.
    services._check_booking_window(dormitory, DAY, slot, NOW)
    # A slot that already started is not.
    started = datetime(2026, 10, 20, 5, 30, tzinfo=UTC)
    with pytest.raises(services.OutsideBookingWindow):
        services._check_booking_window(dormitory, DAY, slot, started)
    # Default horizon is 7 days: today (19th) up to the 25th.
    services._check_booking_window(dormitory, date(2026, 10, 25), slot, NOW)
    with pytest.raises(services.OutsideBookingWindow):
        services._check_booking_window(dormitory, date(2026, 10, 26), slot, NOW)


# --- book_slots ----------------------------------------------------------------


def credit(resident, amount):
    LedgerEntry.objects.create(resident=resident, amount=amount, kind=LedgerEntry.Kind.CREDIT)


def balance(resident):
    return LedgerEntry.objects.balance(resident)


def test_book_one_slot_charges_the_price(resident, machine, slot):
    credit(resident, 120)
    [booking] = services.book_slots(resident, machine, DAY, [slot], now=NOW)
    assert booking.status == Booking.Status.ACTIVE
    assert booking.price_rub == 50
    assert balance(resident) == 70
    charge = LedgerEntry.objects.get(kind=LedgerEntry.Kind.BOOKING)
    assert (charge.booking, charge.amount, charge.created_by) == (booking, -50, None)


def test_book_two_consecutive_slots_charges_100(resident, machine, slot, slot_10):
    credit(resident, 100)
    # Order of the selection does not matter.
    bookings = services.book_slots(resident, machine, DAY, [slot_10, slot], now=NOW)
    assert [b.slot for b in bookings] == [slot, slot_10]
    assert len({b.group_id for b in bookings}) == 1
    charges = LedgerEntry.objects.filter(kind=LedgerEntry.Kind.BOOKING)
    assert sorted(c.amount for c in charges) == [-50, -50]
    assert {c.booking for c in charges} == set(bookings)
    assert balance(resident) == 0


def test_separate_bookings_get_separate_groups(resident, machine, slot, slot_10):
    credit(resident, 100)
    [first] = services.book_slots(resident, machine, DAY, [slot], now=NOW)
    [second] = services.book_slots(resident, machine, DAY, [slot_10], now=NOW)
    assert first.group_id != second.group_id


def test_insufficient_balance_books_nothing(resident, machine, slot, slot_10):
    credit(resident, 99)
    with pytest.raises(services.InsufficientBalance):
        services.book_slots(resident, machine, DAY, [slot, slot_10], now=NOW)
    assert not Booking.objects.exists()
    assert balance(resident) == 99


def test_taken_slot_is_reported_and_not_charged(resident, other_resident, machine, slot):
    credit(resident, 50)
    credit(other_resident, 50)
    services.book_slots(resident, machine, DAY, [slot], now=NOW)
    with pytest.raises(services.SlotUnavailable):
        services.book_slots(other_resident, machine, DAY, [slot], now=NOW)
    assert balance(other_resident) == 50


def test_consecutive_booking_is_all_or_nothing(resident, other_resident, machine, slot, slot_10):
    credit(resident, 100)
    credit(other_resident, 50)
    services.book_slots(other_resident, machine, DAY, [slot_10], now=NOW)
    with pytest.raises(services.SlotUnavailable):
        services.book_slots(resident, machine, DAY, [slot, slot_10], now=NOW)
    # The free 08:00 slot was not booked either.
    assert Booking.objects.filter(resident=resident).count() == 0
    assert balance(resident) == 100


def test_cancelled_slot_can_be_booked_again(resident, other_resident, machine, slot):
    credit(resident, 50)
    credit(other_resident, 50)
    [booking] = services.book_slots(resident, machine, DAY, [slot], now=NOW)
    booking.status = Booking.Status.CANCELLED
    booking.cancelled_at = NOW
    booking.save()
    services.book_slots(other_resident, machine, DAY, [slot], now=NOW)


def test_free_dormitory_creates_no_charge(dormitory, resident, machine, slot):
    dormitory.price_per_slot = 0
    dormitory.save()
    [booking] = services.book_slots(resident, machine, DAY, [slot], now=NOW)
    assert booking.price_rub == 0
    assert not LedgerEntry.objects.exists()


def test_book_rejects_other_dormitory(resident, other_dormitory, slot):
    credit(resident, 50)
    foreign_machine = Machine.objects.create(dormitory=other_dormitory, number=9)
    with pytest.raises(services.WrongDormitory):
        services.book_slots(resident, foreign_machine, DAY, [slot], now=NOW)


def test_book_rejects_inactive_machine(resident, machine, slot):
    credit(resident, 50)
    machine.active = False
    machine.save()
    with pytest.raises(services.MachineUnavailable):
        services.book_slots(resident, machine, DAY, [slot], now=NOW)


@pytest.mark.parametrize("day", [date(2026, 10, 18), date(2026, 10, 26)])
def test_book_rejects_days_outside_window(resident, machine, slot, day):
    credit(resident, 50)
    with pytest.raises(services.OutsideBookingWindow):
        services.book_slots(resident, machine, day, [slot], now=NOW)


def test_book_rejects_gaps(resident, machine, slot, slot_10, slot_12):
    credit(resident, 100)
    with pytest.raises(services.SlotsNotConsecutive):
        services.book_slots(resident, machine, DAY, [slot, slot_12], now=NOW)


def test_book_needs_a_slot(resident, machine):
    with pytest.raises(ValueError):
        services.book_slots(resident, machine, DAY, [], now=NOW)


# --- Cancellation --------------------------------------------------------------

# DAY 08:00 Moscow is 05:00 UTC; with the default 2 h cutoff, refunds end at 03:00 UTC.
CUTOFF = datetime(2026, 10, 20, 3, 0, tzinfo=UTC)


def make_staff(dormitory, role, username):
    user = User.objects.create_user(username=username, password="123456")
    user.groups.add(Group.objects.get(name=role))
    StaffProfile.objects.create(user=user, dormitory=dormitory)
    return user


@pytest.fixture
def booked(resident, machine, slot):
    """A 50 RUB booking for DAY 08:00, paid from a 50 RUB credit."""
    credit(resident, 50)
    [booking] = services.book_slots(resident, machine, DAY, [slot], now=NOW)
    return booking


def refunds():
    return LedgerEntry.objects.filter(kind=LedgerEntry.Kind.REFUND)


def test_refund_due_respects_cutoff(booked):
    assert services.refund_due(booked, CUTOFF)
    assert not services.refund_due(booked, CUTOFF + timedelta(seconds=1))


def test_refund_due_uses_dormitory_cutoff(booked, dormitory):
    dormitory.cancellation_cutoff_hours = 0
    dormitory.save()
    booked.refresh_from_db()
    assert services.refund_due(booked, booked.starts_at)


@pytest.mark.parametrize("now", [NOW, CUTOFF])
def test_cancel_before_cutoff_refunds(booked, resident, now):
    refund = services.cancel_booking(booked, actor=resident.user, now=now)
    booked.refresh_from_db()
    assert booked.status == Booking.Status.CANCELLED
    assert booked.cancelled_at == now
    assert (refund.kind, refund.amount, refund.booking) == (LedgerEntry.Kind.REFUND, 50, booked)
    assert refund.created_by is None
    assert balance(resident) == 50


def test_refund_returns_price_paid_even_if_price_changed(booked, resident, dormitory):
    dormitory.price_per_slot = 80
    dormitory.save()
    refund = services.cancel_booking(booked, actor=resident.user, now=NOW)
    assert refund.amount == 50


def test_cancel_after_cutoff_frees_slot_without_refund(booked, resident, other_resident, slot):
    late = CUTOFF + timedelta(minutes=1)
    assert services.cancel_booking(booked, actor=resident.user, now=late) is None
    booked.refresh_from_db()
    assert booked.status == Booking.Status.CANCELLED
    assert not refunds().exists()
    assert balance(resident) == 0
    # Someone else can take the freed slot.
    credit(other_resident, 50)
    services.book_slots(other_resident, booked.machine, DAY, [slot], now=late)


def test_cannot_cancel_after_start(booked, resident):
    with pytest.raises(services.TooLateToCancel):
        services.cancel_booking(booked, actor=resident.user, now=booked.starts_at)
    booked.refresh_from_db()
    assert booked.status == Booking.Status.ACTIVE


def test_cannot_cancel_completed_booking(booked, resident):
    booked.status = Booking.Status.COMPLETED
    booked.save()
    with pytest.raises(services.TooLateToCancel):
        services.cancel_booking(booked, actor=resident.user, now=NOW)


def test_no_double_refund(booked, resident):
    services.cancel_booking(booked, actor=resident.user, now=NOW)
    # Even with a stale copy that still says "active".
    with pytest.raises(services.AlreadyCancelled):
        services.cancel_booking(booked, actor=resident.user, now=NOW)
    assert refunds().count() == 1
    assert balance(resident) == 50


def test_other_resident_cannot_cancel(booked, other_resident):
    with pytest.raises(services.NotAllowed):
        services.cancel_booking(booked, actor=other_resident.user, now=NOW)
    booked.refresh_from_db()
    assert booked.status == Booking.Status.ACTIVE


def test_inactive_owner_cannot_cancel(booked, resident):
    resident.user.is_active = False
    resident.user.save()
    with pytest.raises(services.NotAllowed):
        services.cancel_booking(booked, actor=resident.user, now=NOW)


@pytest.mark.parametrize("role", [roles.MANAGER, roles.ADMIN])
def test_staff_of_same_dormitory_can_cancel(booked, dormitory, role):
    staff = make_staff(dormitory, role, "staff")
    refund = services.cancel_booking(booked, actor=staff, reason="Pipe burst", now=NOW)
    assert refund.created_by == staff
    booked.refresh_from_db()
    assert booked.status == Booking.Status.CANCELLED_BY_ADMIN
    assert booked.cancel_reason == "Pipe burst"


def test_staff_of_other_dormitory_cannot_cancel(booked, other_dormitory):
    staff = make_staff(other_dormitory, roles.ADMIN, "foreign-admin")
    with pytest.raises(services.NotAllowed):
        services.cancel_booking(booked, actor=staff, now=NOW)


def test_staff_profile_without_role_cannot_cancel(booked, dormitory):
    user = User.objects.create_user(username="no-role", password="123456")
    StaffProfile.objects.create(user=user, dormitory=dormitory)
    with pytest.raises(services.NotAllowed):
        services.cancel_booking(booked, actor=user, now=NOW)


def test_cancel_group_cancels_future_slots(resident, machine, slot, slot_10, slot_12):
    credit(resident, 150)
    bookings = services.book_slots(resident, machine, DAY, [slot, slot_10, slot_12], now=NOW)
    # 08:00 has started; 10:00 is past its cutoff; 12:00 is refunded.
    now = datetime(2026, 10, 20, 5, 30, tzinfo=UTC)
    cancelled = services.cancel_group(bookings[0].group_id, actor=resident.user, now=now)
    assert [b.slot for b in cancelled] == [slot_10, slot_12]
    statuses = {b.slot: b.status for b in Booking.objects.all()}
    assert statuses == {
        slot: Booking.Status.ACTIVE,
        slot_10: Booking.Status.CANCELLED,
        slot_12: Booking.Status.CANCELLED,
    }
    assert [r.booking.slot for r in refunds()] == [slot_12]
    assert balance(resident) == 50


def test_cancel_group_checks_permission(resident, other_resident, machine, slot):
    credit(resident, 50)
    [booking] = services.book_slots(resident, machine, DAY, [slot], now=NOW)
    with pytest.raises(services.NotAllowed):
        services.cancel_group(booking.group_id, actor=other_resident.user, now=NOW)
    booking.refresh_from_db()
    assert booking.status == Booking.Status.ACTIVE


# --- Several machines at once ------------------------------------------------------


@pytest.fixture
def machine2(dormitory):
    return Machine.objects.create(dormitory=dormitory, number=2)


def test_book_two_machines_for_two_slots(resident, machine, machine2, slot, slot_10):
    credit(resident, 200)
    groups = services.book_machines(resident, [machine2, machine], DAY, [slot, slot_10], now=NOW)
    assert [g[0].machine for g in groups] == [machine, machine2]  # machine order
    assert all(len(g) == 2 for g in groups)
    # Each machine is its own group (own key, own cancel button).
    assert len({b.group_id for g in groups for b in g}) == 2
    assert balance(resident) == 0


def test_several_machines_need_the_whole_amount(resident, machine, machine2, slot, slot_10):
    credit(resident, 199)
    with pytest.raises(services.InsufficientBalance):
        services.book_machines(resident, [machine, machine2], DAY, [slot, slot_10], now=NOW)
    assert not Booking.objects.exists()
    assert balance(resident) == 199


def test_several_machines_are_all_or_nothing(
    resident, other_resident, machine, machine2, slot, slot_10
):
    credit(resident, 200)
    credit(other_resident, 50)
    services.book_slots(other_resident, machine2, DAY, [slot_10], now=NOW)
    with pytest.raises(services.SlotUnavailable):
        services.book_machines(resident, [machine, machine2], DAY, [slot, slot_10], now=NOW)
    assert not Booking.objects.filter(resident=resident).exists()
    assert balance(resident) == 200


def test_same_machine_twice_is_booked_once(resident, machine, slot):
    credit(resident, 100)
    groups = services.book_machines(resident, [machine, machine], DAY, [slot], now=NOW)
    assert len(groups) == 1
    assert balance(resident) == 50


def test_inactive_machine_in_the_list_books_nothing(resident, machine, machine2, slot):
    credit(resident, 100)
    machine2.active = False
    machine2.save()
    with pytest.raises(services.MachineUnavailable):
        services.book_machines(resident, [machine, machine2], DAY, [slot], now=NOW)
    assert not Booking.objects.exists()


# --- Staff cancellations (stage 1a) --------------------------------------------------


def test_staff_must_give_a_reason(booked, dormitory):
    staff = make_staff(dormitory, roles.ADMIN, "boss")
    for reason in ("", "   "):
        with pytest.raises(services.ReasonRequired):
            services.cancel_booking(booked, actor=staff, reason=reason, now=NOW)
    booked.refresh_from_db()
    assert booked.status == Booking.Status.ACTIVE
    assert not AuditEvent.objects.exists()


def test_resident_cancellation_needs_no_reason_and_is_not_audited(booked, resident):
    services.cancel_booking(booked, actor=resident.user, now=NOW)
    booked.refresh_from_db()
    assert booked.status == Booking.Status.CANCELLED
    assert booked.cancel_reason == ""
    assert not AuditEvent.objects.exists()


def test_staff_cancellation_is_audited_once(booked, dormitory):
    staff = make_staff(dormitory, roles.ADMIN, "boss")
    services.cancel_booking(booked, actor=staff, reason="Flood", now=NOW)
    event = AuditEvent.objects.get()
    assert (event.action, event.actor, event.reason) == ("booking.cancel_by_staff", staff, "Flood")
    assert event.before["status"] == "active"
    assert event.after["status"] == "cancelled_by_admin"
    assert event.after["refund_rub"] == 50
    assert event.dormitory == dormitory


def test_full_refund_ignores_the_cutoff(booked, dormitory, resident):
    staff = make_staff(dormitory, roles.ADMIN, "boss")
    late = booked.starts_at - timedelta(minutes=30)  # inside the 2-hour cutoff
    assert services.cancel_booking(booked, actor=staff, reason="x", now=late) is None
    credit(resident, 50)  # the first cancellation was (correctly) not refunded
    booked2 = services.book_slots(resident, booked.machine, booked.date, [booked.slot], now=NOW)[0]
    refund = services.cancel_booking(booked2, actor=staff, reason="x", full_refund=True, now=late)
    assert refund.amount == 50
    event = AuditEvent.objects.get(target_id=str(booked2.pk))
    assert event.after["full_refund"] is True


def test_managers_cannot_give_full_refunds(booked, dormitory):
    manager = make_staff(dormitory, roles.MANAGER, "keys")
    with pytest.raises(services.NotAllowed):
        services.cancel_booking(booked, actor=manager, reason="x", full_refund=True, now=NOW)


def test_admin_cancellation_frees_the_slot(booked, dormitory, other_resident):
    staff = make_staff(dormitory, roles.ADMIN, "boss")
    services.cancel_booking(booked, actor=staff, reason="x", now=NOW)
    credit(other_resident, 50)
    services.book_slots(other_resident, booked.machine, booked.date, [booked.slot], now=NOW)


def test_admin_cancelled_booking_cannot_be_cancelled_again(booked, dormitory, resident):
    staff = make_staff(dormitory, roles.ADMIN, "boss")
    services.cancel_booking(booked, actor=staff, reason="x", now=NOW)
    with pytest.raises(services.AlreadyCancelled):
        services.cancel_booking(booked, actor=resident.user, now=NOW)


def test_database_requires_reason_for_admin_cancellation(booked):
    from django.db import IntegrityError, transaction

    booked.status = Booking.Status.CANCELLED_BY_ADMIN
    booked.cancelled_at = NOW
    with pytest.raises(IntegrityError), transaction.atomic():
        booked.save()
