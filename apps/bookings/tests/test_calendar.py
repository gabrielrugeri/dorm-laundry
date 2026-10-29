"""Tests for the .ics calendar export. Every name here is fake."""

from datetime import date, time, timedelta

import pytest
from django.urls import reverse

from apps.bookings import calendar, ics, services
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
    event = calendar.event_for([group], dormitory)
    event.summary = "A, B; C"
    body = ics.booking_calendar(event, uid_domain="example.org")
    assert "SUMMARY:A\\, B\\; C\r\n" in body
    assert all(len(line.encode()) <= 75 for line in body.split("\r\n"))
    assert "LOCATION:Dorm\\; No. 1\\, Building Long" in unfold(body)


def test_slot_ending_at_midnight_ends_next_day(client, resident, machine, dormitory):
    """22:00–00:00 must end at 00:00 of the *next* day in the calendar file."""
    from apps.bookings.availability import local_today

    LedgerEntry.objects.create(resident=resident, kind="credit", amount=50)
    late = TimeSlot.objects.create(dormitory=dormitory, start_time=time(22, 0))
    day = local_today(dormitory) + timedelta(days=2)
    booking = services.book_slots(resident, machine, day, [late])[0]
    client.force_login(resident.user)
    body = unfold(client.get(calendar_url(booking.group_id)).content.decode())
    next_day = day + timedelta(days=1)
    assert f"DTSTART;TZID=Europe/Moscow:{day:%Y%m%d}T220000\r\n" in body
    assert f"DTEND;TZID=Europe/Moscow:{next_day:%Y%m%d}T000000\r\n" in body


# --- File name and "Add to calendar" links -------------------------------------


def test_file_name_has_dormitory_code_day_hours_and_machine(client, resident, group, dormitory):
    client.force_login(resident.user)
    response = client.get(calendar_url(group[0].group_id))
    day = group[0].date.isoformat()
    assert dormitory.code == "TES"  # filled in from the slug "test"
    assert f'filename="laundry-TES-{day}-08-12-M1.ics"' in response["Content-Disposition"]


def test_file_name_for_a_booking_ending_at_midnight(dormitory, machine, resident):
    late = TimeSlot.objects.create(dormitory=dormitory, start_time=time(22, 0))
    booking = Booking(machine=machine, slot=late, date=date(2026, 10, 29), resident=resident)
    booking.starts_at, booking.ends_at = late.bounds(booking.date)
    event = calendar.event_for([BookingGroup(group_id="g1", bookings=[booking])], dormitory)
    assert calendar.filename(event) == "laundry-TES-2026-10-29-22-00-M1.ics"


def test_google_and_outlook_links_match_the_file(client, resident, group):
    from urllib.parse import parse_qs, urlsplit

    client.force_login(resident.user)
    client.cookies["django_language"] = "en"
    response = client.get(reverse("bookings:detail", kwargs={"group_id": group[0].group_id}))
    links = response.context["calendar"]
    day = group[0].date

    google = urlsplit(links["google"])
    assert google.netloc == "calendar.google.com"
    query = parse_qs(google.query)
    # 08:00–12:00 Moscow time is 05:00–09:00 UTC.
    assert query["dates"] == [f"{day:%Y%m%d}T050000Z/{day:%Y%m%d}T090000Z"]
    assert query["text"] == ["Laundry: Machine 1"]

    outlook = urlsplit(links["outlook"])
    assert outlook.netloc == "outlook.live.com"
    query = parse_qs(outlook.query)
    assert query["startdt"] == [f"{day.isoformat()}T08:00:00+03:00"]
    assert query["enddt"] == [f"{day.isoformat()}T12:00:00+03:00"]

    assert links["ics"] == calendar_url(group[0].group_id)
    html = response.content.decode()
    assert 'rel="noopener noreferrer"' in html
    assert resident.full_name not in links["google"] + links["outlook"]


def test_cancelled_booking_has_no_calendar_menu(client, resident, group):
    services.cancel_group(group[0].group_id, actor=resident.user)
    client.force_login(resident.user)
    response = client.get(reverse("bookings:detail", kwargs={"group_id": group[0].group_id}))
    assert response.context["calendar"] is None


@pytest.fixture
def two_machines(resident, machine, slot, dormitory):
    """Machines 1 and 3 booked together for the same slot."""
    from apps.bookings.availability import local_today
    from apps.dorms.models import Machine

    LedgerEntry.objects.create(resident=resident, kind="credit", amount=100)
    third = Machine.objects.create(dormitory=dormitory, number=3)
    day = local_today(dormitory) + timedelta(days=2)
    return services.book_machines(resident, [machine, third], day, [slot])


def test_machines_booked_together_get_one_event(client, resident, two_machines):
    client.force_login(resident.user)
    client.cookies["django_language"] = "en"
    ids = "&".join(f"g={group[0].group_id}" for group in two_machines)
    response = client.get(f"{reverse('bookings:confirmed')}?{ids}")
    together = response.context["calendar_together"]
    assert together is not None
    assert all(cal is None for _group, cal in response.context["rows"])

    file = client.get(together["ics"])
    assert file.status_code == 200
    day = two_machines[0][0].date.isoformat()
    assert f'filename="laundry-TES-{day}-08-10-M1-M3.ics"' in file["Content-Disposition"]
    body = unfold(file.content.decode())
    assert body.count("BEGIN:VEVENT") == 1
    assert "SUMMARY:Laundry: Machine 1\\, Machine 3\r\n" in body


def test_combined_file_only_for_own_bookings(client, other_resident, two_machines):
    client.force_login(other_resident.user)
    ids = "&".join(f"g={group[0].group_id}" for group in two_machines)
    assert client.get(f"{reverse('bookings:calendar_together')}?{ids}").status_code == 404
