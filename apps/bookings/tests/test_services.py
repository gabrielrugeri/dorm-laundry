"""Tests for the booking service. Every name and code here is fake.

Times are passed with `now=` so the tests do not depend on the real clock.
Slots are local Moscow time (UTC+3): 08:00 local is 05:00 UTC.
"""

from datetime import UTC, date, datetime, time

import pytest
from django.utils import translation

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
    foreign_machine = Machine.objects.create(dormitory=other_dormitory, label="Elsewhere")
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
    foreign_machine = Machine.objects.create(dormitory=other_dormitory, label="Elsewhere")
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
