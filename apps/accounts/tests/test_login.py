import pytest
from django.urls import reverse

PIN = "123456"  # The conftest fixtures' PIN.
LOGIN = reverse("accounts:login")


@pytest.fixture(autouse=True)
def login_dormitory(settings, dormitory):
    settings.DEFAULT_DORMITORY_SLUG = dormitory.slug


def post_login(client, code, pin, **extra):
    return client.post(LOGIN, {"username": code, "password": pin}, **extra)


def test_login_page_renders(client):
    response = client.get(LOGIN)
    assert response.status_code == 200
    assert 'name="username"' in response.content.decode()


def test_resident_logs_in(client, resident):
    response = post_login(client, resident.student_code, PIN)
    assert response.status_code == 302
    assert response.wsgi_request.user == resident.user


def test_login_applies_resident_language(client, resident):
    resident.language = "en"
    resident.save()
    response = post_login(client, resident.student_code, PIN)
    assert response.cookies["django_language"].value == "en"


def _error_page(client, code, pin):
    response = post_login(client, code, pin)
    assert response.status_code == 200
    html = response.content.decode()
    # The submitted code is echoed back in the form, and CSRF tokens differ per
    # response; remove both before comparing.
    lines = html.replace(code, "CODE").splitlines()
    return [line for line in lines if "csrf" not in line.lower()]


def test_unknown_code_and_wrong_pin_look_identical(client, resident):
    """The login form must not reveal which student codes exist."""
    wrong_pin = _error_page(client, resident.student_code, "999999")
    unknown_code = _error_page(client, "NOSUCHCODE", PIN)
    assert wrong_pin == unknown_code


def test_inactive_resident_gets_generic_error(client, resident):
    resident.user.is_active = False
    resident.user.save()
    response = post_login(client, resident.student_code, PIN)
    assert response.status_code == 200
    assert not response.wsgi_request.user.is_authenticated


# Login limits: apps/accounts/tests/test_ratelimit.py.


def test_logout_requires_post(client, resident):
    client.force_login(resident.user)
    assert client.get(reverse("accounts:logout")).status_code == 405
    client.post(reverse("accounts:logout"))
    assert "_auth_user_id" not in client.session
