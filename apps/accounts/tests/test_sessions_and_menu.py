"""Login length per role, the remembered language and the identity menu.
Every name here is fake."""

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.accounts import roles
from apps.accounts.sessions import REFRESHED_ON
from apps.keylog.tests.test_services import make_staff

PIN = "123456"
LOGIN = reverse("accounts:login")
LANGUAGE = reverse("accounts:set_language")
DAY = 60 * 60 * 24


@pytest.fixture(autouse=True)
def login_dormitory(settings, dormitory):
    settings.DEFAULT_DORMITORY_SLUG = dormitory.slug


def test_residents_stay_logged_in_for_30_days(client, resident):
    client.post(LOGIN, {"username": resident.student_code, "password": PIN})
    assert client.session.get_expiry_age() == 30 * DAY
    assert client.session[REFRESHED_ON] == timezone.localdate().isoformat()


@pytest.mark.parametrize("role", [roles.ADMIN, roles.MANAGER])
def test_staff_sessions_end_after_12_hours(client, dormitory, role):
    staff = make_staff(dormitory, "staffer", role=role)
    staff.set_password("a-staff-password")
    staff.save()
    client.post(LOGIN, {"username": "staffer", "password": "a-staff-password"})
    assert 12 * 60 * 60 - 60 <= client.session.get_expiry_age() <= 12 * 60 * 60


def test_resident_session_is_refreshed_once_a_day(client, resident):
    client.force_login(resident.user)
    session = client.session
    session[REFRESHED_ON] = (timezone.localdate() - timedelta(days=1)).isoformat()
    session.save()
    client.get(reverse("bookings:mine"))
    assert client.session[REFRESHED_ON] == timezone.localdate().isoformat()


def test_staff_session_is_not_extended(client, dormitory):
    staff = make_staff(dormitory, "boss", role=roles.ADMIN)
    client.force_login(staff)
    client.get(reverse("manage:residents"))
    assert REFRESHED_ON not in client.session


def test_language_choice_is_saved_for_residents(client, resident):
    client.force_login(resident.user)
    response = client.post(LANGUAGE, {"language": "en", "next": "/"})
    assert response.status_code == 302
    assert response.cookies["django_language"].value == "en"
    resident.refresh_from_db()
    assert resident.language == "en"


def test_unknown_language_is_not_saved(client, resident):
    client.force_login(resident.user)
    client.post(LANGUAGE, {"language": "xx", "next": "/"})
    resident.refresh_from_db()
    assert resident.language == "ru"


def test_language_switch_works_without_login(client, db):
    response = client.post(LANGUAGE, {"language": "en", "next": "/"})
    assert response.cookies["django_language"].value == "en"


def test_header_shows_own_name_and_room_only(client, resident, other_resident):
    client.force_login(resident.user)
    html = client.get(reverse("bookings:mine")).content.decode()
    assert f"{resident.full_name} · {resident.room}" in html
    assert other_resident.full_name not in html
    assert reverse("ledger:balance") in html


def test_names_are_shown_as_stored_in_every_language(client, resident):
    resident.full_name = "Иван Тестов"
    resident.save()
    client.force_login(resident.user)
    client.cookies["django_language"] = "en"
    assert "Иван Тестов · 101" in client.get(reverse("ledger:balance")).content.decode()


def test_staff_header_shows_username(client, dormitory):
    client.force_login(make_staff(dormitory, "boss", role=roles.ADMIN))
    assert ">boss<" in client.get(reverse("manage:residents")).content.decode()
