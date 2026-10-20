"""The admin area and its audit log page. Every name here is fake."""

import re

import pytest
from django.urls import reverse

from apps.accounts import roles
from apps.audit.services import record, snapshot
from apps.keylog.tests.test_services import make_staff

INDEX = reverse("manage:index")
RESIDENTS = reverse("manage:residents")
AUDIT = reverse("manage:audit")


@pytest.fixture
def boss(dormitory):
    return make_staff(dormitory, "boss", role=roles.ADMIN)


@pytest.fixture
def boss_client(client, boss):
    client.force_login(boss)
    client.cookies["django_language"] = "en"
    return client


@pytest.fixture
def room_change(boss, resident):
    before = snapshot(resident)
    resident.room = "305"
    resident.save()
    return record(
        actor=boss,
        action="admin.change",
        target=resident,
        before=before,
        after=snapshot(resident),
        reason="Moved rooms",
    )


@pytest.mark.parametrize("url", [RESIDENTS, AUDIT])
def test_admins_only(client, dormitory, resident, url):
    assert client.get(url).status_code == 302  # anonymous: to login
    client.force_login(resident.user)
    assert client.get(url).status_code == 403
    client.force_login(make_staff(dormitory, "keys", role=roles.MANAGER))
    assert client.get(url).status_code == 403
    client.force_login(make_staff(dormitory, "boss", role=roles.ADMIN))
    assert client.get(url).status_code == 200


def test_audit_log_shows_changes(boss_client, room_change):
    response = boss_client.get(AUDIT)
    assert list(response.context["page"]) == [room_change]
    html = response.content.decode()
    assert "Changed by a developer" in html
    assert "Moved rooms" in html
    assert "305" in html and "101" in html


def test_audit_log_is_scoped_to_the_dormitory(boss_client, other_dormitory, room_change):
    stranger = make_staff(other_dormitory, "stranger", role=roles.ADMIN)
    record(actor=stranger, action="admin.add", dormitory=other_dormitory)
    record(actor=stranger, action="admin.add")  # no dormitory, other dormitory's staff
    assert list(boss_client.get(AUDIT).context["page"]) == [room_change]


def test_own_staff_events_without_dormitory_are_shown(boss_client, boss):
    event = record(actor=boss, action="admin.add")
    assert event in boss_client.get(AUDIT).context["page"]


def test_filters(boss_client, boss, room_change):
    other = record(actor=boss, action="ledger.payment", reason="Cash")
    assert list(boss_client.get(AUDIT, {"action": "ledger.payment"}).context["page"]) == [other]
    assert list(boss_client.get(AUDIT, {"q": "moved"}).context["page"]) == [room_change]
    assert (
        list(boss_client.get(AUDIT, {"from": "2000-01-01", "to": "2000-01-02"}).context["page"])
        == []
    )
    # Invalid dates are ignored, not errors.
    assert boss_client.get(AUDIT, {"from": "not-a-date"}).status_code == 200


def test_staff_page_links_admins_to_management(boss_client):
    html = boss_client.get(reverse("core:staff_home")).content.decode()
    assert INDEX in html


def test_admin_area_loads_nothing_from_third_party_hosts(boss_client, room_change):
    external = re.compile(r'(?:src|href)\s*=\s*["\'](?:https?:)?//', re.IGNORECASE)
    for url in (RESIDENTS, AUDIT):
        assert not external.search(boss_client.get(url).content.decode())


def test_manage_starts_on_the_resident_list(boss_client):
    response = boss_client.get(INDEX)
    assert response.status_code == 302 and response.url == RESIDENTS
