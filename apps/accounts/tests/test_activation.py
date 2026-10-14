from datetime import datetime, timedelta
from unittest import mock

import pytest
from django.contrib.auth.tokens import default_token_generator
from django.test import RequestFactory
from django.urls import reverse

from apps.accounts.activation import activation_url
from apps.accounts.models import User

NEW_PIN = "482913"


@pytest.fixture(autouse=True)
def login_dormitory(settings, dormitory):
    settings.DEFAULT_DORMITORY_SLUG = dormitory.slug


@pytest.fixture
def new_resident(resident):
    """A resident created by the admin who has not chosen a PIN yet."""
    resident.user.set_unusable_password()
    resident.user.save()
    return resident


def link_for(user):
    return activation_url(RequestFactory().get("/"), user).removeprefix("http://testserver")


def open_link(client, link):
    """Follow the link; Django moves the token into the session and redirects."""
    response = client.get(link)
    assert response.status_code == 302
    return response.url


def test_activation_sets_pin_and_logs_in(client, new_resident):
    form_url = open_link(client, link_for(new_resident.user))
    assert "set-pin" in form_url
    response = client.post(form_url, {"pin1": NEW_PIN, "pin2": NEW_PIN})
    assert response.status_code == 302
    assert response.url == reverse("core:home")
    assert response.wsgi_request.user == new_resident.user
    new_resident.user.refresh_from_db()
    assert new_resident.user.check_password(NEW_PIN)


def test_activation_applies_resident_language(client, new_resident):
    new_resident.language = "en"
    new_resident.save()
    form_url = open_link(client, link_for(new_resident.user))
    response = client.post(form_url, {"pin1": NEW_PIN, "pin2": NEW_PIN})
    assert response.cookies["django_language"].value == "en"


def test_link_works_only_once(client, new_resident):
    link = link_for(new_resident.user)
    client.post(open_link(client, link), {"pin1": NEW_PIN, "pin2": NEW_PIN})
    client.logout()
    response = client.get(link)
    assert response.status_code == 200
    assert not response.context["validlink"]


def test_link_expires(client, new_resident, settings):
    settings.PASSWORD_RESET_TIMEOUT = 60
    link = link_for(new_resident.user)
    # The token generator uses naive local time internally.
    five_minutes_later = datetime.now() + timedelta(minutes=5)
    with mock.patch.object(default_token_generator, "_now", return_value=five_minutes_later):
        response = client.get(link)
    assert not response.context["validlink"]


def test_tampered_link_is_rejected(client, new_resident):
    response = client.get(link_for(new_resident.user)[:-3] + "xx/")
    assert response.status_code == 200
    assert not response.context["validlink"]


def test_invalid_link_page_does_not_mention_passwords(client, new_resident):
    client.cookies["django_language"] = "en"
    response = client.get(link_for(new_resident.user)[:-3] + "xx/")
    assert "<title>Link not valid" in response.content.decode()
    assert "password" not in response.content.decode().lower()


def test_links_are_for_residents_only(client, db):
    staff = User.objects.create_user(username="staff-member")
    response = client.get(link_for(staff))
    assert response.status_code == 200
    assert not response.context["validlink"]


@pytest.mark.parametrize(
    ("pin1", "pin2"), [("123456", "123456"), ("4829", "4829"), (NEW_PIN, "482914")]
)
def test_bad_pins_are_rejected(client, new_resident, pin1, pin2):
    form_url = open_link(client, link_for(new_resident.user))
    response = client.post(form_url, {"pin1": pin1, "pin2": pin2})
    assert response.status_code == 200
    assert response.context["form"].errors
    new_resident.user.refresh_from_db()
    assert not new_resident.user.has_usable_password()


def test_new_pin_works_for_login(client, new_resident):
    client.post(open_link(client, link_for(new_resident.user)), {"pin1": NEW_PIN, "pin2": NEW_PIN})
    client.logout()
    response = client.post(
        reverse("accounts:login"),
        {"username": new_resident.student_code, "password": NEW_PIN},
    )
    assert response.wsgi_request.user == new_resident.user


def test_admin_reset_pin_action(admin_client, resident):
    response = admin_client.post(
        reverse("admin:accounts_resident_changelist"),
        {"action": "reset_pins", "_selected_action": [resident.pk]},
    )
    assert response.status_code == 200
    resident.user.refresh_from_db()
    assert not resident.user.has_usable_password()
    (listed_resident, url), *_ = response.context["links"]
    assert listed_resident == resident
    assert "/account/activate/" in url


def test_admin_create_links_keeps_current_pin(admin_client, resident):
    response = admin_client.post(
        reverse("admin:accounts_resident_changelist"),
        {"action": "create_activation_links", "_selected_action": [resident.pk]},
    )
    assert response.status_code == 200
    resident.user.refresh_from_db()
    assert resident.user.has_usable_password()
    assert len(response.context["links"]) == 1
