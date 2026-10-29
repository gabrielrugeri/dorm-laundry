"""Key handling is on hold: with KEYS_ENABLED=false (the default) the key
schedule leaves the navigation and its pages do not exist."""

import uuid

import pytest
from django.conf import settings as django_settings
from django.urls import reverse

from apps.accounts import roles
from apps.keylog.tests.test_services import make_staff

STAFF_HOME = reverse("core:staff_home")
RESIDENTS = reverse("manage:residents")


def test_keys_are_off_by_default():
    assert django_settings.KEYS_ENABLED is False


@pytest.fixture
def boss_client(client, dormitory):
    client.force_login(make_staff(dormitory, "boss", role=roles.ADMIN))
    client.cookies["django_language"] = "en"
    return client


@pytest.fixture
def manager_client(client, dormitory):
    client.force_login(make_staff(dormitory, "keys", role=roles.MANAGER))
    client.cookies["django_language"] = "en"
    return client


def test_admin_navigation_has_no_keys(boss_client):
    html = boss_client.get(RESIDENTS).content.decode()
    assert ">Keys<" not in html
    assert f'href="{STAFF_HOME}"' not in html


def test_admin_navigation_shows_keys_when_switched_on(boss_client, settings):
    settings.KEYS_ENABLED = True
    assert ">Keys<" in boss_client.get(RESIDENTS).content.decode()


def test_admins_start_in_the_admin_area(boss_client):
    response = boss_client.get(STAFF_HOME)
    assert response.status_code == 302 and response.url == reverse("manage:index")


def test_managers_see_a_short_note(manager_client):
    response = manager_client.get(STAFF_HOME)
    assert response.status_code == 200
    assert "Not available yet" in response.content.decode()
    assert "keys_out" not in response.context


def test_key_actions_do_not_exist(manager_client):
    url = reverse("keylog:action", kwargs={"group_id": uuid.uuid4(), "action": "take"})
    assert manager_client.post(url).status_code == 404


def test_staff_home_still_needs_staff(client, resident):
    assert client.get(STAFF_HOME).status_code == 302  # anonymous: to login
    client.force_login(resident.user)
    assert client.get(STAFF_HOME).status_code == 403
