from datetime import UTC, date, datetime

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.bookings.models import Booking
from apps.dorms.models import Machine


def test_starts_and_ends_at_are_derived_in_utc(make_booking):
    booking = make_booking(date=date(2026, 10, 14))
    # Slot 08:00–10:00 Moscow time = 05:00–07:00 UTC.
    assert booking.starts_at == datetime(2026, 10, 14, 5, 0, tzinfo=UTC)
    assert booking.ends_at == datetime(2026, 10, 14, 7, 0, tzinfo=UTC)


def test_database_rejects_double_booking(make_booking, other_resident):
    make_booking()
    with pytest.raises(IntegrityError), transaction.atomic():
        make_booking(resident=other_resident)


@pytest.mark.parametrize("status", [Booking.Status.ACTIVE, Booking.Status.COMPLETED])
def test_occupied_statuses_block_the_slot(make_booking, other_resident, status):
    first = make_booking()
    first.status = status
    first.save()
    with pytest.raises(IntegrityError), transaction.atomic():
        make_booking(resident=other_resident)


def test_slot_can_be_rebooked_after_cancellation(make_booking, other_resident):
    first = make_booking()
    first.status = Booking.Status.CANCELLED
    first.cancelled_at = timezone.now()
    first.save()
    make_booking(resident=other_resident)
    # And several cancelled bookings may exist for the same slot.
    second = Booking.objects.get(status=Booking.Status.ACTIVE)
    second.status = Booking.Status.CANCELLED
    second.cancelled_at = timezone.now()
    second.save()


def test_other_machine_same_slot_is_fine(make_booking, dormitory):
    make_booking()
    make_booking(machine=Machine.objects.create(dormitory=dormitory, label="Machine 2"))


def test_cancelled_booking_needs_cancelled_at(make_booking):
    booking = make_booking()
    booking.status = Booking.Status.CANCELLED
    with pytest.raises(IntegrityError), transaction.atomic():
        booking.save()


def test_clean_rejects_mixed_dormitories(make_booking, other_dormitory):
    foreign_machine = Machine.objects.create(dormitory=other_dormitory, label="Elsewhere")
    booking = make_booking()
    booking.machine = foreign_machine
    with pytest.raises(ValidationError):
        booking.clean()
