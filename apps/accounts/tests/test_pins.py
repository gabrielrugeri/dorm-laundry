"""PINs are hashed with a server-side secret (the pepper). Every value here is fake."""

import pytest
from django.contrib.auth.hashers import make_password
from django.urls import reverse

from apps.accounts import pins
from apps.accounts.hashers import ALGORITHM

PIN = "123456"


@pytest.fixture(autouse=True)
def login_dormitory(settings, dormitory):
    settings.DEFAULT_DORMITORY_SLUG = dormitory.slug


def login(client, code, pin):
    return client.post(reverse("accounts:login"), {"username": code, "password": pin})


def test_pins_are_stored_with_the_pepper(resident):
    stored = resident.user.password
    assert stored.startswith(ALGORITHM + "$")
    assert PIN not in stored
    assert pins.check_pin(resident.user, PIN)
    assert not pins.check_pin(resident.user, "654321")


def test_without_the_right_pepper_no_pin_matches(resident, settings):
    """A stolen database alone is not enough to check PINs."""
    settings.PIN_PEPPER = "a-different-secret-" + "x" * 30
    assert not pins.check_pin(resident.user, PIN)


def test_old_pins_without_the_pepper_are_upgraded_at_login(client, resident):
    user = resident.user
    user.password = make_password(PIN, hasher="pbkdf2_sha256")  # stored before the pepper
    user.save()
    assert login(client, resident.student_code, PIN).status_code == 302
    user.refresh_from_db()
    assert user.password.startswith(ALGORITHM + "$")
    client.logout()
    assert login(client, resident.student_code, PIN).status_code == 302


def test_django_never_rehashes_a_pin_without_the_pepper(resident):
    """User.check_password must not let Django's automatic re-hashing drop it."""
    user = resident.user
    assert user.check_password(PIN)
    user.refresh_from_db()
    assert user.password.startswith(ALGORITHM + "$")


def test_unknown_codes_cost_a_pin_hash(client, db, monkeypatch):
    calls = []
    monkeypatch.setattr(pins, "dummy_check", lambda pin: calls.append(pin))
    login(client, "NOSUCHCODE", PIN)
    assert calls == [PIN]


def test_staff_passwords_keep_the_normal_hasher(dormitory):
    from apps.keylog.tests.test_services import make_staff

    staff = make_staff(dormitory, "boss")
    staff.set_password("a-long-staff-password")
    staff.save()
    assert not staff.password.startswith(ALGORITHM)
    assert staff.check_password("a-long-staff-password")
