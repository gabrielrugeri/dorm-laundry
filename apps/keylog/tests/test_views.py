"""Tests for the manager's key screen. Every name here is fake."""

from datetime import time, timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.bookings.availability import local_today
from apps.bookings.models import Booking
from apps.dorms.models import TimeSlot
from apps.keylog.models import KeyLog
from apps.keylog.tests.test_services import make_staff

STAFF_HOME = reverse("core:staff_home")


@pytest.fixture
def manager(dormitory):
    return make_staff(dormitory, "manager")


@pytest.fixture
def staff_client(client, manager):
    client.force_login(manager)
    client.cookies["django_language"] = "en"
    return client


@pytest.fixture
def today(dormitory):
    return local_today(dormitory)


@pytest.fixture
def todays_group(make_booking, dormitory, today):
    """Today 08:00–12:00 (two slots) for 'Ivan Testov', room 101."""
    first = make_booking(date=today)
    slot_10 = TimeSlot.objects.create(dormitory=dormitory, start_time=time(10, 0))
    make_booking(date=today, slot=slot_10, group_id=first.group_id)
    return first.group_id


def action_url(group_id, action):
    return reverse("keylog:action", kwargs={"group_id": group_id, "action": action})


def test_schedule_lists_todays_bookings_with_names(staff_client, todays_group):
    response = staff_client.get(STAFF_HOME)
    assert response.status_code == 200
    rows = response.context["rows"]
    assert len(rows) == 1 and rows[0].status == "waiting"
    html = response.content.decode()
    assert "08:00–12:00" in html
    assert "Ivan Testov" in html and "room 101" in html


def test_cancelled_bookings_are_not_listed(staff_client, todays_group):
    Booking.objects.filter(group_id=todays_group).update(
        status="cancelled", cancelled_at=timezone.now()
    )
    assert staff_client.get(STAFF_HOME).context["rows"] == []


def test_take_and_return_buttons(staff_client, manager, todays_group):
    response = staff_client.post(action_url(todays_group, "take"), {"note": "card left"})
    assert response.status_code == 302
    log = KeyLog.objects.get()
    assert log.taken_at and log.recorded_by == manager and log.note == "card left"
    assert staff_client.get(STAFF_HOME).context["keys_out"][0].log == log

    staff_client.post(action_url(todays_group, "return"))
    log.refresh_from_db()
    assert log.returned_at
    assert staff_client.get(STAFF_HOME).context["keys_out"] == []


def test_htmx_tap_returns_the_schedule_partial(staff_client, todays_group):
    response = staff_client.post(action_url(todays_group, "take"), HTTP_HX_REQUEST="true")
    assert response.status_code == 200
    html = response.content.decode()
    assert "<html" not in html
    assert "Key returned" in html  # the next action is offered


def test_undo_button(staff_client, todays_group):
    staff_client.post(action_url(todays_group, "take"))
    assert staff_client.get(STAFF_HOME).context["rows"][0].can_undo
    staff_client.post(action_url(todays_group, "undo"))
    assert KeyLog.objects.get().taken_at is None


def test_return_before_take_shows_error(staff_client, todays_group):
    response = staff_client.post(action_url(todays_group, "return"), follow=True)
    assert "has not been taken" in response.content.decode()


def test_overdue_key_from_yesterday_is_listed_first(
    staff_client, make_booking, dormitory, today, todays_group, other_resident
):
    yesterday_booking = make_booking(date=today - timedelta(days=1), resident=other_resident)
    KeyLog.objects.create(booking=yesterday_booking, taken_at=yesterday_booking.starts_at)
    staff_client.post(action_url(todays_group, "take"))
    keys = staff_client.get(STAFF_HOME).context["keys_out"]
    assert [k.booking.resident for k in keys][0] == other_resident
    assert keys[0].overdue


def test_day_tabs_yesterday_today_tomorrow(staff_client, today):
    response = staff_client.get(STAFF_HOME, {"day": "2000-01-01"})
    assert response.context["day"] == today
    assert response.context["days"] == [today + timedelta(days=n) for n in (-1, 0, 1)]


def test_unknown_action_is_404(staff_client, todays_group):
    assert staff_client.post(action_url(todays_group, "explode")).status_code == 404


def test_actions_need_post(staff_client, todays_group):
    assert staff_client.get(action_url(todays_group, "take")).status_code == 405


def test_residents_cannot_open_or_use_the_key_screen(client, resident, todays_group):
    client.force_login(resident.user)
    assert client.get(STAFF_HOME).status_code == 403
    assert client.post(action_url(todays_group, "take")).status_code == 403
    assert not KeyLog.objects.exists()


def test_staff_of_other_dormitory_get_404(client, other_dormitory, todays_group):
    client.force_login(make_staff(other_dormitory, "stranger"))
    assert client.post(action_url(todays_group, "take")).status_code == 404
    response = client.get(STAFF_HOME)
    assert response.context["rows"] == []


def test_anonymous_is_sent_to_login(client, todays_group):
    response = client.post(action_url(todays_group, "take"))
    assert response.status_code == 302
    assert response.url.startswith(reverse("accounts:login"))


def test_key_screen_in_russian(staff_client, todays_group):
    staff_client.cookies["django_language"] = "ru"
    staff_client.post(action_url(todays_group, "take"))
    html = staff_client.get(STAFF_HOME).content.decode()
    assert "Ключ возвращён" in html
    assert "комната 101" in html
