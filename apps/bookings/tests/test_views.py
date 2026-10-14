"""Tests for the resident booking screens. Every name and code here is fake.

Bookings are made for "tomorrow" in the dormitory's timezone, so the tests do
not depend on the time of day they run at.
"""

from datetime import time, timedelta

import pytest
from django.urls import reverse

from apps.bookings import availability
from apps.bookings.models import Booking
from apps.dorms.models import Machine, TimeSlot
from apps.ledger.models import LedgerEntry

HOME = reverse("core:home")


@pytest.fixture
def tomorrow(dormitory):
    return availability.local_today(dormitory) + timedelta(days=1)


@pytest.fixture
def slots(dormitory, slot):
    """08:00, 10:00 and 12:00, two hours each."""
    return [
        slot,
        TimeSlot.objects.create(dormitory=dormitory, start_time=time(10, 0)),
        TimeSlot.objects.create(dormitory=dormitory, start_time=time(12, 0)),
    ]


@pytest.fixture
def machine2(dormitory):
    return Machine.objects.create(dormitory=dormitory, label="Machine 2")


@pytest.fixture
def logged_in(client, resident):
    LedgerEntry.objects.create(resident=resident, kind="credit", amount=200)
    client.force_login(resident.user)
    return client


def book_url(day, slot):
    return reverse("bookings:book", kwargs={"day": day, "slot_id": slot.pk})


def grid_rows(client, day):
    response = client.get(HOME, {"day": day.isoformat()})
    assert response.status_code == 200
    return {row.slot.pk: row for row in response.context["rows"]}


# --- Grid ------------------------------------------------------------------------


def test_grid_counts_free_machines(logged_in, slots, machine, machine2, other_resident, tomorrow):
    Booking.objects.create(
        machine=machine, slot=slots[0], date=tomorrow, resident=other_resident, price_rub=50
    )
    rows = grid_rows(logged_in, tomorrow)
    assert (rows[slots[0].pk].free, rows[slots[0].pk].total) == (1, 2)
    assert rows[slots[1].pk].free == 2
    assert not rows[slots[0].pk].mine


def test_grid_marks_own_bookings(logged_in, resident, slots, machine, tomorrow):
    Booking.objects.create(
        machine=machine, slot=slots[1], date=tomorrow, resident=resident, price_rub=50
    )
    rows = grid_rows(logged_in, tomorrow)
    assert rows[slots[1].pk].mine
    assert not rows[slots[0].pk].mine


def test_cancelled_bookings_free_the_machine(logged_in, slots, machine, other_resident, tomorrow):
    booking = Booking.objects.create(
        machine=machine, slot=slots[0], date=tomorrow, resident=other_resident, price_rub=50
    )
    booking.status = Booking.Status.CANCELLED
    booking.cancelled_at = booking.starts_at
    booking.save()
    assert grid_rows(logged_in, tomorrow)[slots[0].pk].free == 1


def test_started_slots_cannot_be_booked(logged_in, dormitory, machine):
    midnight = TimeSlot.objects.create(dormitory=dormitory, start_time=time(0, 0))
    today = availability.local_today(dormitory)
    row = grid_rows(logged_in, today)[midnight.pk]
    assert row.started and not row.bookable


def test_grid_offers_only_days_in_the_horizon(logged_in, dormitory, slots):
    response = logged_in.get(HOME, {"day": "2000-01-01"})
    assert response.context["day"] == availability.local_today(dormitory)
    assert len(response.context["days"]) == dormitory.booking_horizon_days


def test_htmx_request_gets_only_the_grid(logged_in, slots, machine, tomorrow):
    response = logged_in.get(HOME, {"day": tomorrow.isoformat()}, HTTP_HX_REQUEST="true")
    html = response.content.decode()
    assert "<html" not in html
    assert book_url(tomorrow, slots[0]) in html


# --- Booking ---------------------------------------------------------------------


def test_booking_page_lists_free_machines_and_lengths(
    logged_in, slots, machine, machine2, other_resident, tomorrow
):
    Booking.objects.create(
        machine=machine, slot=slots[1], date=tomorrow, resident=other_resident, price_rub=50
    )
    form = logged_in.get(book_url(tomorrow, slots[0])).context["form"]
    assert form.runs == {str(machine.pk): (machine, 1), str(machine2.pk): (machine2, 3)}
    assert [value for value, _label in form.fields["count"].choices] == [1, 2, 3]


def test_book_two_consecutive_slots(logged_in, resident, slots, machine, tomorrow):
    response = logged_in.post(book_url(tomorrow, slots[0]), {"machine": machine.pk, "count": 2})
    assert response.status_code == 302
    bookings = Booking.objects.filter(resident=resident)
    assert bookings.count() == 2
    assert len({b.group_id for b in bookings}) == 1
    assert LedgerEntry.objects.balance(resident) == 100
    assert response.url == reverse("bookings:detail", kwargs={"group_id": bookings[0].group_id})

    detail = logged_in.get(response.url).content.decode()
    assert "08:00–12:00" in detail


def test_count_longer_than_machine_is_free_is_refused(
    logged_in, resident, slots, machine, machine2, other_resident, tomorrow
):
    Booking.objects.create(
        machine=machine, slot=slots[1], date=tomorrow, resident=other_resident, price_rub=50
    )
    response = logged_in.post(book_url(tomorrow, slots[0]), {"machine": machine.pk, "count": 2})
    assert response.status_code == 200
    assert response.context["form"].errors["count"]
    assert not Booking.objects.filter(resident=resident).exists()


def test_insufficient_balance_shows_message(client, resident, slots, machine, tomorrow):
    client.force_login(resident.user)  # balance 0
    response = client.post(book_url(tomorrow, slots[0]), {"machine": machine.pk, "count": 1})
    assert response.status_code == 200
    assert response.context["form"].non_field_errors()
    assert not Booking.objects.exists()


def test_slot_taken_meanwhile_shows_message(
    logged_in, resident, slots, machine, other_resident, tomorrow, monkeypatch
):
    """Another resident books between the page loading and the form submit."""
    page = logged_in.get(book_url(tomorrow, slots[0]))
    assert page.context["form"].runs
    real_free_runs = availability.free_runs

    def stale_free_runs(*args):
        runs = real_free_runs(*args)
        Booking.objects.create(
            machine=machine, slot=slots[0], date=tomorrow, resident=other_resident, price_rub=50
        )
        return runs

    monkeypatch.setattr(availability, "free_runs", stale_free_runs)
    response = logged_in.post(book_url(tomorrow, slots[0]), {"machine": machine.pk, "count": 1})
    assert response.status_code == 200
    assert response.context["form"].non_field_errors()
    assert not Booking.objects.filter(resident=resident).exists()
    assert LedgerEntry.objects.balance(resident) == 200


def test_slot_of_other_dormitory_is_404(logged_in, other_dormitory, tomorrow):
    foreign = TimeSlot.objects.create(dormitory=other_dormitory, start_time=time(8, 0))
    assert logged_in.get(book_url(tomorrow, foreign)).status_code == 404


def test_booking_outside_the_window_is_refused(logged_in, dormitory, slots, machine):
    too_far = availability.local_today(dormitory) + timedelta(days=30)
    response = logged_in.get(book_url(too_far, slots[0]))
    assert response.context["unavailable"]
    assert "form" not in response.context


def test_invalid_date_in_url_is_404(logged_in, slots):
    assert logged_in.get(f"/book/2026-13-45/{slots[0].pk}/").status_code == 404


def test_other_residents_booking_detail_is_404(client, other_resident, make_booking):
    booking = make_booking()
    client.force_login(other_resident.user)
    url = reverse("bookings:detail", kwargs={"group_id": booking.group_id})
    assert client.get(url).status_code == 404


def test_pages_are_translated_to_russian(logged_in, slots, machine, machine2, tomorrow):
    logged_in.cookies["django_language"] = "ru"
    grid = logged_in.get(HOME, {"day": tomorrow.isoformat()}).content.decode()
    assert "свободно 2 из 2" in grid
    page = logged_in.get(book_url(tomorrow, slots[0])).content.decode()
    assert "Начало: 08:00–10:00" in page
    assert "50 ₽ за слот. Ваш баланс: 200 ₽." in page
    assert "3 слота (08:00–14:00)" in page
