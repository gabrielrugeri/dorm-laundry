from datetime import UTC, datetime, time, timedelta

import pytest
from django.db import IntegrityError, transaction

from apps.bookings.models import Booking
from apps.dorms.models import TimeSlot
from apps.keylog.models import KeyLog


def test_due_at_is_end_of_last_slot_in_group(make_booking, dormitory):
    first = make_booking()
    next_slot = TimeSlot.objects.create(dormitory=dormitory, start_time=time(10, 0))
    make_booking(slot=next_slot, group_id=first.group_id)
    log = KeyLog.objects.create(booking=first)
    # 08:00–12:00 Moscow = until 09:00 UTC.
    assert log.due_at == datetime(2026, 10, 14, 9, 0, tzinfo=UTC)


def test_cancelled_slots_do_not_extend_due_at(make_booking, dormitory):
    first = make_booking()
    next_slot = TimeSlot.objects.create(dormitory=dormitory, start_time=time(10, 0))
    second = make_booking(slot=next_slot, group_id=first.group_id)
    second.status = Booking.Status.CANCELLED
    second.cancelled_at = second.starts_at
    second.save()
    log = KeyLog.objects.create(booking=first)
    assert log.due_at == first.ends_at


def test_overdue_only_when_taken_and_not_returned(make_booking):
    log = KeyLog.objects.create(booking=make_booking())
    later = log.due_at + timedelta(minutes=1)
    assert not log.is_overdue(now=later)  # never taken
    log.taken_at = log.booking.starts_at
    assert log.is_overdue(now=later)
    assert not log.is_overdue(now=log.due_at)
    log.returned_at = later
    assert not log.is_overdue(now=later + timedelta(hours=1))


def test_cannot_return_before_taking(make_booking):
    booking = make_booking()
    with pytest.raises(IntegrityError), transaction.atomic():
        KeyLog.objects.create(booking=booking, returned_at=booking.starts_at)
    with pytest.raises(IntegrityError), transaction.atomic():
        KeyLog.objects.create(
            booking=booking,
            taken_at=booking.starts_at,
            returned_at=booking.starts_at - timedelta(minutes=5),
        )


def test_one_log_per_booking(make_booking):
    booking = make_booking()
    KeyLog.objects.create(booking=booking)
    with pytest.raises(IntegrityError), transaction.atomic():
        KeyLog.objects.create(booking=booking)
