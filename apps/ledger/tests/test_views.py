"""Tests for the resident balance page and header balance. Fake data only."""

import pytest
from django.urls import reverse

from apps.ledger.models import LedgerEntry

BALANCE = reverse("ledger:balance")


@pytest.fixture
def history(resident, other_resident, make_booking):
    LedgerEntry.objects.create(resident=resident, kind="credit", amount=200, note="Cash at desk")
    booking = make_booking()
    LedgerEntry.objects.create(resident=resident, kind="booking", amount=-50, booking=booking)
    LedgerEntry.objects.create(resident=other_resident, kind="credit", amount=999)


def test_balance_page_shows_own_history(client, resident, history):
    client.force_login(resident.user)
    client.cookies["django_language"] = "en"
    response = client.get(BALANCE)
    assert response.status_code == 200
    assert response.context["balance"] == 150
    assert [e.amount for e in response.context["page"]] == [-50, 200]
    html = response.content.decode()
    assert "150 RUB" in html
    assert "−50 RUB" in html and "+200 RUB" in html
    assert "Cash at desk" in html
    assert "999" not in html


def test_balance_in_russian(client, resident, history):
    client.force_login(resident.user)
    client.cookies["django_language"] = "ru"
    assert "150 ₽" in client.get(BALANCE).content.decode()


def test_header_shows_balance_to_residents_only(client, resident, history, admin_user):
    client.force_login(resident.user)
    assert client.get(reverse("bookings:mine")).context["resident_balance"] == 150
    client.force_login(admin_user)
    assert "resident_balance" not in client.get("/admin/").context


def test_balance_page_is_paginated(client, resident):
    for _ in range(25):
        LedgerEntry.objects.create(resident=resident, kind="credit", amount=1)
    client.force_login(resident.user)
    assert len(client.get(BALANCE).context["page"]) == 20
    assert len(client.get(BALANCE, {"page": 2}).context["page"]) == 5
