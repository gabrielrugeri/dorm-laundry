"""Tests for "My bookings" and cancelling from it. Every name here is fake."""

from datetime import time, timedelta

import pytest
from django.urls import reverse

from apps.bookings import availability, services
from apps.bookings.models import Booking
from apps.dorms.models import TimeSlot
from apps.ledger.models import LedgerEntry

MINE = reverse("bookings:mine")


@pytest.fixture
def credited(resident):
    LedgerEntry.objects.create(resident=resident, kind="credit", amount=200)
    return resident


@pytest.fixture
def logged_in(client, credited):
    client.force_login(credited.user)
    return client


@pytest.fixture
def tomorrow(dormitory):
    return availability.local_today(dormitory) + timedelta(days=1)


@pytest.fixture
def two_slot_group(credited, machine, slot, dormitory, tomorrow):
    """Tomorrow 08:00–12:00, booked through the service (so it is charged)."""
    slot_10 = TimeSlot.objects.create(dormitory=dormitory, start_time=time(10, 0))
    return services.book_slots(credited, machine, tomorrow, [slot, slot_10])


def cancel_url(group_id):
    return reverse("bookings:cancel", kwargs={"group_id": group_id})


def test_my_bookings_lists_upcoming_groups_once(logged_in, two_slot_group):
    response = logged_in.get(MINE)
    upcoming = response.context["upcoming"]
    assert [g.group_id for g in upcoming] == [two_slot_group[0].group_id]
    assert "08:00–12:00" in response.content.decode()


def test_my_bookings_shows_only_own_bookings(client, other_resident, two_slot_group):
    client.force_login(other_resident.user)
    response = client.get(MINE)
    assert response.context["upcoming"] == []
    assert response.context["past"] == []


def test_cancel_page_announces_refund(logged_in, two_slot_group):
    response = logged_in.get(cancel_url(two_slot_group[0].group_id))
    assert response.context["refund_total"] == 100
    assert all(due for _booking, due in response.context["refunds"])


def test_cancel_refunds_and_frees_slots(logged_in, resident, two_slot_group):
    assert LedgerEntry.objects.balance(resident) == 100
    response = logged_in.post(cancel_url(two_slot_group[0].group_id))
    assert response.status_code == 302
    assert LedgerEntry.objects.balance(resident) == 200
    assert not Booking.objects.filter(status=Booking.Status.ACTIVE).exists()
    mine = logged_in.get(MINE)
    assert mine.context["upcoming"] == []
    assert mine.context["past"][0].is_cancelled


def test_cancel_after_cutoff_has_no_refund(logged_in, resident, dormitory, two_slot_group):
    dormitory.cancellation_cutoff_hours = 48  # tomorrow's slots are within 48 hours
    dormitory.save()
    response = logged_in.get(cancel_url(two_slot_group[0].group_id))
    assert response.context["refund_total"] == 0
    logged_in.post(cancel_url(two_slot_group[0].group_id))
    assert LedgerEntry.objects.balance(resident) == 100  # charged, not refunded
    assert not Booking.objects.filter(status=Booking.Status.ACTIVE).exists()


def test_cancel_needs_post(logged_in, two_slot_group):
    logged_in.get(cancel_url(two_slot_group[0].group_id))
    assert Booking.objects.filter(status=Booking.Status.ACTIVE).count() == 2


def test_cancelling_twice_is_harmless(logged_in, resident, two_slot_group):
    url = cancel_url(two_slot_group[0].group_id)
    logged_in.post(url)
    response = logged_in.post(url)
    assert response.status_code == 302
    assert LedgerEntry.objects.balance(resident) == 200


def test_started_booking_cannot_be_cancelled(logged_in, resident, machine, dormitory):
    midnight = TimeSlot.objects.create(dormitory=dormitory, start_time=time(0, 0))
    today = availability.local_today(dormitory)
    booking = Booking.objects.create(
        machine=machine, slot=midnight, date=today, resident=resident, price_rub=50
    )
    response = logged_in.post(cancel_url(booking.group_id))
    assert response.status_code == 302
    booking.refresh_from_db()
    assert booking.status == Booking.Status.ACTIVE


def test_other_residents_cannot_cancel(client, other_resident, two_slot_group):
    client.force_login(other_resident.user)
    response = client.post(cancel_url(two_slot_group[0].group_id))
    assert response.status_code == 404
    assert Booking.objects.filter(status=Booking.Status.ACTIVE).count() == 2


def test_cancel_page_in_russian(logged_in, two_slot_group):
    logged_in.cookies["django_language"] = "ru"
    html = logged_in.get(cancel_url(two_slot_group[0].group_id)).content.decode()
    assert "возврат 50 ₽" in html
    assert "Отменить и вернуть 100 ₽" in html
    assert "за 2 часа до начала" in html
