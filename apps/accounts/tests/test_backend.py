import pytest
from django.contrib.auth import authenticate
from django.core.exceptions import ValidationError
from django.test import override_settings

from apps.accounts.validators import validate_pin

PIN = "123456"  # The conftest fixtures' PIN.


@pytest.mark.parametrize("pin", ["482913", "100200", "135790"])
def test_valid_pins(pin):
    validate_pin(pin)


@pytest.mark.parametrize(
    "pin", ["", "12345", "1234567", "12a456", " 48291", "000000", "777777", "123456", "654321"]
)
def test_invalid_pins(pin):
    with pytest.raises(ValidationError):
        validate_pin(pin)


@pytest.fixture(autouse=True)
def login_dormitory(settings, dormitory):
    settings.DEFAULT_DORMITORY_SLUG = dormitory.slug


def test_resident_logs_in_with_code_and_pin(resident):
    assert authenticate(username=resident.student_code, password=PIN) == resident.user


def test_surrounding_spaces_in_code_are_ignored(resident):
    assert authenticate(username=f" {resident.student_code} ", password=PIN) == resident.user


def test_wrong_pin_or_unknown_code_fails(resident):
    assert authenticate(username=resident.student_code, password="999999") is None
    assert authenticate(username="NOPE", password=PIN) is None


def test_inactive_resident_cannot_log_in(resident):
    resident.user.is_active = False
    resident.user.save()
    assert authenticate(username=resident.student_code, password=PIN) is None


def test_resident_of_other_dormitory_cannot_log_in_here(other_dormitory):
    from conftest import make_resident

    stranger = make_resident(other_dormitory, "X0001")
    assert authenticate(username=stranger.student_code, password=PIN) is None
    with override_settings(DEFAULT_DORMITORY_SLUG=other_dormitory.slug):
        assert authenticate(username=stranger.student_code, password=PIN) == stranger.user
