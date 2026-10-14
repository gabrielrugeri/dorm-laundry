"""Tests for the .ics calendar export. Every name here is fake."""

from datetime import date, time, timedelta

import pytest
from django.urls import reverse

from apps.bookings import ics, services
from apps.bookings.groups import BookingGroup
from apps.bookings.models import Booking
from apps.dorms.models import TimeSlot
from apps.ledger.models import LedgerEntry


@pytest.fixture
def group(resident, machine, slot, dormitory):
    """Two slots, 08:00–12:00 Moscow time, a few days ahead."""
    LedgerEntry.objects.create(resident=resident, kind="credit", amount=100)
    slot_10 = TimeSlot.objects.create(dormitory=dormitory, start_time=time(10, 0))
    from apps.bookings.availability import local_today

    day = local_today(dormitory) + timedelta(days=2)
    return services.book_slots(resident, machine, day, [slot, slot_10])


def calendar_url(group_id):
    return reverse("bookings:calendar", kwargs={"group_id": group_id})


def unfold(text):
    return text.replace("\r\n ", "")


def test_calendar_file_uses_moscow_time(client, resident, group):
    client.force_login(resident.user)
    client.cookies["django_language"] = "en"
    response = client.get(calendar_url(group[0].group_id))
    assert response.status_code == 200
    assert response["Content-Type"] == "text/calendar; charset=utf-8"
    assert "attachment" in response["Content-Disposition"]
    body = unfold(response.content.decode())
    day = group[0].date.strftime("%Y%m%d")
    # Wall-clock Moscow times, not UTC.
    assert f"DTSTART;TZID=Europe/Moscow:{day}T080000\r\n" in body
    assert f"DTEND;TZID=Europe/Moscow:{day}T120000\r\n" in body
    assert "TZOFFSETTO:+0300\r\n" in body
    assert f"UID:{group[0].group_id}@testserver\r\n" in body
    assert "SUMMARY:Laundry: Machine 1\r\n" in body
    assert body.startswith("BEGIN:VCALENDAR\r\n")
    assert body.endswith("END:VCALENDAR\r\n")


def test_calendar_file_has_no_personal_data(client, resident, group):
    resident.room = "Room-Z9"  # distinctive, so digits elsewhere cannot match
    resident.save()
    client.force_login(resident.user)
    body = client.get(calendar_url(group[0].group_id)).content.decode()
    assert resident.full_name not in body
    assert resident.room not in body
    assert resident.student_code not in body


def test_only_the_owner_gets_the_calendar_file(client, other_resident, group):
    client.force_login(other_resident.user)
    assert client.get(calendar_url(group[0].group_id)).status_code == 404


def test_cancelled_booking_has_no_calendar_file(client, resident, group):
    services.cancel_group(group[0].group_id, actor=resident.user)
    client.force_login(resident.user)
    assert client.get(calendar_url(group[0].group_id)).status_code == 404


def test_text_is_escaped_and_long_lines_folded(dormitory, machine, slot, resident):
    dormitory.name = "Dorm; No. 1, Building " + "Long " * 20
    booking = Booking(machine=machine, slot=slot, date=date(2026, 10, 20), resident=resident)
    booking.starts_at, booking.ends_at = slot.bounds(booking.date)
    group = BookingGroup(group_id="g1", bookings=[booking])
    body = ics.booking_calendar(group, dormitory, uid_domain="example.org", summary="A, B; C")
    assert "SUMMARY:A\\, B\\; C\r\n" in body
    assert all(len(line.encode()) <= 75 for line in body.split("\r\n"))
    assert "LOCATION:Dorm\\; No. 1\\, Building Long" in unfold(body)
