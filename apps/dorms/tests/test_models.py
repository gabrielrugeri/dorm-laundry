from datetime import UTC, date, datetime, time

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from apps.dorms.models import Dormitory, Machine, TimeSlot


def test_slot_bounds_are_in_dormitory_timezone(slot):
    start, end = slot.bounds(date(2026, 10, 14))
    # 08:00 Moscow (UTC+3) is 05:00 UTC.
    assert start == datetime(2026, 10, 14, 5, 0, tzinfo=UTC)
    assert end == datetime(2026, 10, 14, 7, 0, tzinfo=UTC)


def test_slot_must_end_same_day(dormitory):
    slot = TimeSlot(dormitory=dormitory, start_time=time(23, 0), duration_minutes=120)
    with pytest.raises(ValidationError):
        slot.full_clean()


def test_slot_label(slot):
    assert str(slot) == "08:00–10:00"


def test_slot_start_unique_per_dormitory(slot, dormitory):
    with pytest.raises(IntegrityError):
        TimeSlot.objects.create(dormitory=dormitory, start_time=time(8, 0))


def test_same_slot_time_allowed_in_other_dormitory(slot, other_dormitory):
    TimeSlot.objects.create(dormitory=other_dormitory, start_time=time(8, 0))


def test_machine_label_unique_per_dormitory(machine, dormitory, other_dormitory):
    Machine.objects.create(dormitory=other_dormitory, label=machine.label)
    with pytest.raises(IntegrityError):
        Machine.objects.create(dormitory=dormitory, label=machine.label)


def test_unknown_timezone_rejected(db):
    dorm = Dormitory(name="X", slug="x", timezone="Mars/Olympus")
    with pytest.raises(ValidationError):
        dorm.full_clean()
