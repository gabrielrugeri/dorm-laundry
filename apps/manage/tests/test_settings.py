"""The money and upload rules screen: admins only, password and reason, extra
confirmation for big jumps, history in plain words. Every name here is fake."""

import pytest
from django.urls import reverse

from apps.accounts import roles
from apps.audit.models import AuditEvent
from apps.dorms import rules
from apps.keylog.tests.test_services import make_staff

PAGE = reverse("manage:settings")
CHANGE = reverse("manage:settings_change")
PASSWORD = "a-staff-password"


@pytest.fixture
def boss(dormitory):
    user = make_staff(dormitory, "boss", role=roles.ADMIN)
    user.set_password(PASSWORD)
    user.save()
    return user


@pytest.fixture
def boss_client(client, boss):
    client.force_login(boss)
    client.cookies["django_language"] = "en"
    return client


def form_data(**changes):
    data = {name: getattr(rules.current(), name) for name in rules.FIELDS}
    data = {name: "" if value is None else value for name, value in data.items()}
    return {**data, "reason": "Decided at the dorm meeting", "password": PASSWORD, **changes}


@pytest.mark.parametrize("url", [PAGE, CHANGE])
def test_admins_only(client, dormitory, resident, url):
    assert client.get(url).status_code == 302
    client.force_login(resident.user)
    assert client.get(url).status_code == 403
    client.force_login(make_staff(dormitory, "keys", role=roles.MANAGER))
    assert client.get(url).status_code == 403


def test_page_shows_rules_in_plain_words(boss_client):
    html = boss_client.get(PAGE).content.decode()
    assert "May go into debt up to" in html and "100 RUB" in html
    assert "credit_limit" not in html
    assert CHANGE in html


def test_change_needs_the_right_password(boss_client):
    page = boss_client.post(CHANGE, form_data(credit_limit=200, password="wrong"))
    assert page.context["form"].errors["password"]
    assert rules.current().credit_limit == 100
    assert not AuditEvent.objects.exists()


def test_change_needs_a_reason(boss_client):
    page = boss_client.post(CHANGE, form_data(credit_limit=200, reason=""))
    assert page.context["form"].errors["reason"]
    assert rules.current().credit_limit == 100


def test_change_is_saved_and_shown_in_the_history(boss_client):
    response = boss_client.post(CHANGE, form_data(credit_limit=200))
    assert response.status_code == 302 and response.url == PAGE
    assert rules.current().credit_limit == 200
    event = AuditEvent.objects.get(action="settings.change")
    assert event.reason == "Decided at the dorm meeting"
    html = boss_client.get(PAGE).content.decode()
    assert "May go into debt up to: 100 RUB → <strong>200 RUB</strong>" in html
    # Also in the general change history.
    assert (
        "Money and upload rules changed"
        in boss_client.get(reverse("manage:audit")).content.decode()
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"credit_limit": 2000},
        {"credit_limit": 0},
        {"credit_limit": ""},
        {"max_receipt_amount": 100},
    ],
    ids=["20x-up", "to-zero", "no-limit", "below-a-tenth"],
)
def test_big_change_needs_an_extra_tick(boss_client, changes):
    page = boss_client.post(CHANGE, form_data(**changes))
    assert page.status_code == 200
    assert "These values change a lot" in page.content.decode()
    assert not AuditEvent.objects.exists()
    boss_client.post(CHANGE, form_data(confirm_big="on", **changes))
    assert AuditEvent.objects.filter(action="settings.change").count() == 1


def test_no_limit_is_shown_in_words(boss_client):
    boss_client.post(CHANGE, form_data(credit_limit="", confirm_big="on"))
    assert rules.current().credit_limit is None
    assert "no limit" in boss_client.get(PAGE).content.decode()


@pytest.mark.parametrize(
    "changes",
    [
        {"credit_limit": 50_000},
        {"max_uploads_per_day": 0},
        {"max_receipt_amount": 3000, "max_credit_per_30_days": 2500},
    ],
    ids=["limit-too-high", "uploads-zero", "30-days-below-receipt"],
)
def test_values_outside_bounds_are_refused(boss_client, changes):
    page = boss_client.post(CHANGE, form_data(confirm_big="on", **changes))
    assert page.status_code == 200 and page.context["form"].errors
    assert not AuditEvent.objects.exists()


def test_nothing_changed_is_not_saved(boss_client):
    page = boss_client.post(CHANGE, form_data())
    assert "Nothing was changed." in page.content.decode()
    assert not AuditEvent.objects.exists()


def test_admin_navigation_has_settings(boss_client):
    assert f'href="{PAGE}"' in boss_client.get(reverse("manage:residents")).content.decode()
