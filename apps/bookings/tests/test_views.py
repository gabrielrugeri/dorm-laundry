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
    return Machine.objects.create(dormitory=dormitory, number=2)


@pytest.fixture
def logged_in(client, resident):
    LedgerEntry.objects.create(resident=resident, kind="credit", amount=200)
    client.force_login(resident.user)
    return client


def book_url(day, slot, length=1):
    url = reverse("bookings:book", kwargs={"day": day, "slot_id": slot.pk})
    return f"{url}?length={length}"


def take(machine, slot, day, resident):
    return Booking.objects.create(
        machine=machine, slot=slot, date=day, resident=resident, price_rub=50
    )


def grid_options(client, day, length=1):
    response = client.get(HOME, {"day": day.isoformat(), "length": length})
    assert response.status_code == 200
    return {o.slot.pk: o for o in response.context["options"]}


# --- Grid ------------------------------------------------------------------------


def test_grid_counts_free_machines(logged_in, slots, machine, machine2, other_resident, tomorrow):
    take(machine, slots[0], tomorrow, other_resident)
    options = grid_options(logged_in, tomorrow)
    assert options[slots[0].pk].free == 1
    assert options[slots[1].pk].free == 2


def test_grid_shows_only_starts_free_for_the_whole_length(
    logged_in, slots, machine, machine2, other_resident, tomorrow
):
    # Machine 1 is busy at 10:00, machine 2 at 12:00.
    take(machine, slots[1], tomorrow, other_resident)
    take(machine2, slots[2], tomorrow, other_resident)
    options = grid_options(logged_in, tomorrow, length=2)
    # 08:00–12:00: only machine 2. 10:00–14:00: nobody. 12:00: run too short.
    assert list(options) == [slots[0].pk]
    assert options[slots[0].pk].free == 1
    assert options[slots[0].pk].end_time == time(12, 0)


def test_runs_that_do_not_fit_in_the_day_are_left_out(logged_in, slots, machine, tomorrow):
    assert list(grid_options(logged_in, tomorrow, length=3)) == [slots[0].pk]


def test_fully_booked_slots_are_left_out(logged_in, slots, machine, other_resident, tomorrow):
    take(machine, slots[0], tomorrow, other_resident)
    assert slots[0].pk not in grid_options(logged_in, tomorrow)


def test_cancelled_bookings_free_the_machine(logged_in, slots, machine, other_resident, tomorrow):
    booking = take(machine, slots[0], tomorrow, other_resident)
    booking.status = Booking.Status.CANCELLED
    booking.cancelled_at = booking.starts_at
    booking.save()
    assert grid_options(logged_in, tomorrow)[slots[0].pk].free == 1


def test_started_slots_are_left_out(logged_in, dormitory, machine):
    midnight = TimeSlot.objects.create(dormitory=dormitory, start_time=time(0, 0))
    today = availability.local_today(dormitory)
    assert midnight.pk not in grid_options(logged_in, today)


def test_own_bookings_of_the_day_are_listed(logged_in, resident, slots, machine, tomorrow):
    take(machine, slots[1], tomorrow, resident)
    response = logged_in.get(HOME, {"day": tomorrow.isoformat()})
    [group] = response.context["own_groups"]
    assert group.bookings[0].slot == slots[1]


def test_length_choices_and_invalid_values(logged_in, dormitory, slots, machine):
    response = logged_in.get(HOME, {"length": "99"})
    assert list(response.context["lengths"]) == [1, 2, 3]
    assert response.context["length"] == 3
    assert logged_in.get(HOME, {"length": "x"}).context["length"] == 1


def test_grid_offers_only_days_in_the_horizon(logged_in, dormitory, slots):
    response = logged_in.get(HOME, {"day": "2000-01-01"})
    assert response.context["day"] == availability.local_today(dormitory)
    assert len(response.context["days"]) == dormitory.booking_horizon_days


def test_htmx_request_gets_only_the_grid(logged_in, slots, machine, tomorrow):
    response = logged_in.get(
        HOME, {"day": tomorrow.isoformat(), "length": 2}, HTTP_HX_REQUEST="true"
    )
    html = response.content.decode()
    assert "<html" not in html
    assert (
        book_url(tomorrow, slots[0], 2).replace("&", "&amp;") in html
        or book_url(tomorrow, slots[0], 2) in html
    )


# --- Slot page -------------------------------------------------------------------


def test_slot_page_lists_every_machine_with_its_state(
    logged_in, dormitory, slots, machine, machine2, other_resident, tomorrow
):
    machine3 = Machine.objects.create(dormitory=dormitory, number=3)
    machine4 = Machine.objects.create(dormitory=dormitory, number=4, active=False)
    take(machine2, slots[0], tomorrow, other_resident)  # booked at the start
    take(machine3, slots[1], tomorrow, other_resident)  # free only until 10:00
    form = logged_in.get(book_url(tomorrow, slots[0], length=2)).context["form"]
    states = {c.machine: (c.state, c.free_until) for c in form.choices}
    assert states == {
        machine: ("free", None),
        machine2: ("booked", None),
        machine3: ("free_until", time(10, 0)),
        machine4: ("out_of_service", None),
    }


def test_book_two_machines_for_two_slots(logged_in, resident, slots, machine, machine2, tomorrow):
    response = logged_in.post(
        book_url(tomorrow, slots[0], length=2), {"machines": [machine.pk, machine2.pk]}
    )
    assert response.status_code == 302
    bookings = Booking.objects.filter(resident=resident)
    assert bookings.count() == 4
    assert len({b.group_id for b in bookings}) == 2  # one group per machine
    assert LedgerEntry.objects.balance(resident) == 0

    confirmation = logged_in.get(response.url)
    assert len(confirmation.context["groups"]) == 2
    assert "08:00–12:00" in confirmation.content.decode()


def test_must_choose_a_machine(logged_in, resident, slots, machine, tomorrow):
    response = logged_in.post(book_url(tomorrow, slots[0]), {})
    assert response.context["form"].errors["machines"]
    assert not Booking.objects.exists()


def test_unavailable_machine_cannot_be_submitted(
    logged_in, resident, slots, machine, machine2, other_resident, tomorrow
):
    take(machine2, slots[0], tomorrow, other_resident)
    response = logged_in.post(book_url(tomorrow, slots[0]), {"machines": [machine2.pk]})
    assert response.context["form"].errors["machines"]
    assert not Booking.objects.filter(resident=resident).exists()


def test_insufficient_balance_shows_message(client, resident, slots, machine, tomorrow):
    from apps.dorms.models import GlobalSettings

    GlobalSettings.objects.update_or_create(pk=1, defaults={"credit_limit": 0})
    client.force_login(resident.user)  # balance 0, no debt allowed
    response = client.post(book_url(tomorrow, slots[0]), {"machines": [machine.pk]})
    assert response.status_code == 200
    assert response.context["form"].non_field_errors()
    assert not Booking.objects.exists()


def test_slot_taken_meanwhile_shows_message(
    logged_in, resident, slots, machine, other_resident, tomorrow, monkeypatch
):
    """Another resident books between the page loading and the form submit."""
    real_choices = availability.machine_choices

    def stale_choices(*args):
        choices = real_choices(*args)
        take(machine, slots[0], tomorrow, other_resident)
        return choices

    monkeypatch.setattr(availability, "machine_choices", stale_choices)
    response = logged_in.post(book_url(tomorrow, slots[0]), {"machines": [machine.pk]})
    assert response.status_code == 200
    assert response.context["form"].non_field_errors()
    assert not Booking.objects.filter(resident=resident).exists()
    assert LedgerEntry.objects.balance(resident) == 200


def test_length_that_does_not_fit_is_refused(logged_in, slots, machine, tomorrow):
    response = logged_in.get(book_url(tomorrow, slots[2], length=2))
    assert response.context["unavailable"]


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


def test_confirmation_shows_only_own_groups(client, other_resident, make_booking):
    booking = make_booking()
    client.force_login(other_resident.user)
    url = reverse("bookings:confirmed") + f"?g={booking.group_id}&g=not-a-uuid"
    assert client.get(url).status_code == 404


def test_other_residents_booking_detail_is_404(client, other_resident, make_booking):
    booking = make_booking()
    client.force_login(other_resident.user)
    url = reverse("bookings:detail", kwargs={"group_id": booking.group_id})
    assert client.get(url).status_code == 404


# --- Language ----------------------------------------------------------------------


def test_pages_are_translated_to_russian(logged_in, slots, machine, machine2, tomorrow):
    logged_in.cookies["django_language"] = "ru"
    grid = logged_in.get(HOME, {"day": tomorrow.isoformat(), "length": 2}).content.decode()
    assert "свободно 2 машины" in grid
    assert "2 слота · 4 ч" in grid
    page = logged_in.get(book_url(tomorrow, slots[0], 2)).content.decode()
    assert "Машина 1" in page and "Машина 2" in page
    assert "08:00–12:00 · 2 слота" in " ".join(page.split())
    assert "100 ₽ за машину на 2 слота." in page
    assert 'data-label="Итого"' in page  # running total label


def test_dates_use_russian_genitive_month(logged_in, dormitory, slots, machine):
    """'14 октября', not '14 Октябрь'."""
    from django.utils import formats, translation

    logged_in.cookies["django_language"] = "ru"
    day = availability.local_today(dormitory) + timedelta(days=1)
    html = logged_in.get(HOME, {"day": day.isoformat()}).content.decode()
    with translation.override("ru"):
        genitive = formats.date_format(day, "j E")
        nominative = formats.date_format(day, "j F")
    assert genitive != nominative  # every Russian month has a different genitive
    assert genitive in html
    assert nominative not in html


def test_booking_page_tells_the_credit_limit(logged_in, slots, tomorrow):
    logged_in.cookies["django_language"] = "en"
    html = logged_in.get(book_url(tomorrow, slots[0])).content.decode()
    assert "You may go into debt up to 100 RUB." in html
