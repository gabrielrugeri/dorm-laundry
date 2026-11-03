"""Residents change their PIN, staff their password. Every value here is fake."""

import pytest
from django.test import Client
from django.urls import reverse

from apps.accounts import pins, roles
from apps.audit.models import AuditEvent
from apps.keylog.tests.test_services import make_staff

PIN = "123456"
NEW_PIN = "246813"
CHANGE_PIN = reverse("accounts:change_pin")
CHANGE_PASSWORD = reverse("accounts:change_password")
STAFF_PASSWORD = "an-old-staff-password-1"


@pytest.fixture(autouse=True)
def login_dormitory(settings, dormitory):
    settings.DEFAULT_DORMITORY_SLUG = dormitory.slug


def change_pin(client, current=PIN, new=NEW_PIN, repeat=None):
    return client.post(
        CHANGE_PIN, {"current": current, "pin1": new, "pin2": new if repeat is None else repeat}
    )


def logged_in_client(resident):
    client = Client()
    response = client.post(
        reverse("accounts:login"), {"username": resident.student_code, "password": PIN}
    )
    assert response.status_code == 302
    return client


def test_resident_changes_pin_and_other_devices_are_logged_out(resident):
    phone, laptop = logged_in_client(resident), logged_in_client(resident)
    response = change_pin(phone)
    assert response.status_code == 302
    resident.user.refresh_from_db()
    assert pins.check_pin(resident.user, NEW_PIN)
    assert resident.user.password.startswith("pin_pbkdf2_sha256$")
    # This device stays logged in; the other one is logged out.
    assert phone.get(reverse("bookings:mine")).status_code == 200
    assert laptop.get(reverse("bookings:mine")).status_code == 302
    event = AuditEvent.objects.get(action="resident.pin_change")
    assert event.actor == resident.user
    assert PIN not in str(event.before) + str(event.after) + event.reason
    assert NEW_PIN not in str(event.before) + str(event.after) + event.reason


@pytest.mark.parametrize(
    "data, field",
    [
        ({"current": "999999"}, "current"),
        ({"new": PIN}, "pin1"),  # the same as the current one
        ({"new": "111111"}, "pin1"),  # too easy
        ({"new": "12345"}, "pin1"),  # not 6 digits
        ({"repeat": "246814"}, "pin2"),
    ],
    ids=["wrong-current", "unchanged", "trivial", "short", "mismatch"],
)
def test_bad_pin_changes_are_refused(client, resident, data, field):
    client.force_login(resident.user)
    response = change_pin(client, **data)
    assert response.status_code == 200
    assert response.context["form"].has_error(field)
    resident.user.refresh_from_db()
    assert pins.check_pin(resident.user, PIN)
    assert not AuditEvent.objects.filter(action="resident.pin_change").exists()


def test_wrong_current_pins_count_toward_the_lock(client, resident):
    """The change page cannot be used to guess PINs either."""
    client.force_login(resident.user)
    for _ in range(5):
        change_pin(client, current="999999")
    response = change_pin(client)  # the right PIN, but locked
    assert response.status_code == 200
    assert "current" in response.context["form"].errors
    resident.user.refresh_from_db()
    assert pins.check_pin(resident.user, PIN)
    other = Client()
    login = other.post(
        reverse("accounts:login"), {"username": resident.student_code, "password": PIN}
    )
    assert login.status_code == 200  # the login page is locked too


def test_staff_change_their_password(dormitory):
    boss = make_staff(dormitory, "boss", role=roles.ADMIN)
    boss.set_password(STAFF_PASSWORD)
    boss.save()
    client, other = Client(), Client()
    for c in (client, other):
        c.post(reverse("accounts:login"), {"username": "boss", "password": STAFF_PASSWORD})
    new = "a-brand-new-staff-password-2"
    response = client.post(
        CHANGE_PASSWORD,
        {"old_password": STAFF_PASSWORD, "new_password1": new, "new_password2": new},
    )
    assert response.status_code == 302
    boss.refresh_from_db()
    assert boss.check_password(new)
    assert client.get(reverse("manage:residents")).status_code == 200
    assert other.get(reverse("manage:residents")).status_code == 302
    assert AuditEvent.objects.filter(action="user.password_change", actor=boss).exists()


def test_wrong_old_passwords_count_toward_the_lock(client, dormitory):
    boss = make_staff(dormitory, "boss", role=roles.ADMIN)
    boss.set_password(STAFF_PASSWORD)
    boss.save()
    client.force_login(boss)
    for _ in range(5):
        client.post(
            CHANGE_PASSWORD, {"old_password": "wrong", "new_password1": "x", "new_password2": "x"}
        )
    login = Client().post(
        reverse("accounts:login"), {"username": "boss", "password": STAFF_PASSWORD}
    )
    assert login.status_code == 200


def test_each_role_sees_only_its_own_page_and_menu_link(client, resident, dormitory):
    client.force_login(resident.user)
    html = client.get(reverse("bookings:mine")).content.decode()
    assert CHANGE_PIN in html and CHANGE_PASSWORD not in html
    assert client.get(CHANGE_PASSWORD).status_code == 403

    client.force_login(make_staff(dormitory, "keys"))
    html = client.get(reverse("core:staff_home")).content.decode()
    assert CHANGE_PASSWORD in html and CHANGE_PIN not in html
    assert client.get(CHANGE_PIN).status_code == 403


def test_anonymous_users_are_sent_to_login(client, db):
    for url in (CHANGE_PIN, CHANGE_PASSWORD):
        assert client.get(url).status_code == 302
