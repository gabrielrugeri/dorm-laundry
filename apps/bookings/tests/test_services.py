"""Tests for the booking service. Every name and code here is fake.

Times are passed with `now=` so the tests do not depend on the real clock.
Slots are local Moscow time (UTC+3): 08:00 local is 05:00 UTC.
"""

from datetime import UTC, date, datetime, time

import pytest
from django.utils import translation

from apps.bookings import services
from apps.dorms.models import Machine, TimeSlot

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
