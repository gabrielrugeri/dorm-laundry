"""Tests for recording key hand-overs. Every name here is fake."""

from datetime import UTC, date, datetime, time, timedelta

import pytest
from django.contrib.auth.models import Group

from apps.accounts import roles
from apps.accounts.models import StaffProfile, User
from apps.bookings.models import Booking
from apps.dorms.models import TimeSlot
from apps.keylog import services
from apps.keylog.models import KeyLog

DAY = date(2026, 10, 20)
# 08:00 Moscow on DAY.
START = datetime(2026, 10, 20, 5, 0, tzinfo=UTC)


def make_staff(dormitory, username, role=roles.MANAGER):
    user = User.objects.create_user(username=username)
    user.groups.add(Group.objects.get(name=role))
    StaffProfile.objects.create(user=user, dormitory=dormitory)
    return user


@pytest.fixture
def manager(dormitory):
    return make_staff(dormitory, "manager")


@pytest.fixture
def group(make_booking, dormitory):
    """08:00–12:00 on DAY: two slots booked together."""
    first = make_booking(date=DAY)
    slot_10 = TimeSlot.objects.create(dormitory=dormitory, start_time=time(10, 0))
    make_booking(date=DAY, slot=slot_10, group_id=first.group_id)
    return first.group_id


def test_take_then_return(manager, group):
    log = services.take_key(group, actor=manager, now=START)
    assert log.taken_at == START and log.returned_at is None
    assert log.booking.starts_at == START  # attached to the first booking
    later = START + timedelta(hours=4)
    log = services.return_key(group, actor=manager, now=later)
    assert log.returned_at == later
    assert log.recorded_by == manager
    assert KeyLog.objects.count() == 1


def test_double_taps_change_nothing(manager, group):
    services.take_key(group, actor=manager, now=START)
    log = services.take_key(group, actor=manager, now=START + timedelta(minutes=1))
    assert log.taken_at == START
    services.return_key(group, actor=manager, now=START + timedelta(hours=1))
    log = services.return_key(group, actor=manager, now=START + timedelta(hours=2))
    assert log.returned_at == START + timedelta(hours=1)


def test_cannot_return_before_taking(manager, group):
    with pytest.raises(services.KeyNotTaken):
        services.return_key(group, actor=manager, now=START)


def test_note_is_appended(manager, group):
    services.take_key(group, actor=manager, note="ID card left", now=START)
    log = services.return_key(group, actor=manager, note="  all fine ", now=START)
    assert log.note == "ID card left\nall fine"


def test_undo_within_window(manager, group):
    services.take_key(group, actor=manager, now=START)
    services.return_key(group, actor=manager, now=START + timedelta(hours=1))
    log = services.undo_last(group, actor=manager, now=START + timedelta(hours=1, minutes=5))
    assert log.returned_at is None and log.taken_at == START
    with pytest.raises(services.NothingToUndo):
        services.undo_last(group, actor=manager, now=START + timedelta(hours=1, minutes=5))


def test_undo_take_within_window(manager, group):
    services.take_key(group, actor=manager, now=START)
    log = services.undo_last(group, actor=manager, now=START + timedelta(minutes=9))
    assert log.taken_at is None


def test_undo_too_late(manager, group):
    services.take_key(group, actor=manager, now=START)
    with pytest.raises(services.NothingToUndo):
        services.undo_last(group, actor=manager, now=START + timedelta(minutes=11))


def test_residents_cannot_record_keys(resident, group):
    with pytest.raises(services.NotAllowed):
        services.take_key(group, actor=resident.user, now=START)


def test_staff_of_other_dormitory_cannot_record_keys(other_dormitory, group):
    stranger = make_staff(other_dormitory, "stranger")
    with pytest.raises(services.NotAllowed):
        services.take_key(group, actor=stranger, now=START)


def test_admin_can_record_keys(dormitory, group):
    admin = make_staff(dormitory, "boss", role=roles.ADMIN)
    assert services.take_key(group, actor=admin, now=START).taken_at == START


def test_cancelled_booking_has_no_key(manager, group):
    Booking.objects.filter(group_id=group).update(status="cancelled", cancelled_at=START)
    with pytest.raises(services.BookingCancelled):
        services.take_key(group, actor=manager, now=START)


def test_can_undo(manager, group):
    assert not services.can_undo(None)
    log = services.take_key(group, actor=manager, now=START)
    assert services.can_undo(log, now=START + timedelta(minutes=10))
    assert not services.can_undo(log, now=START + timedelta(minutes=11))
