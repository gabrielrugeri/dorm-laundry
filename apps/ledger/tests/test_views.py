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


# --- One line per booking ---------------------------------------------------------


@pytest.fixture
def four_hours(resident, machine, slot, dormitory):
    """A 4-hour booking (two slots, two charges of 50) on machine 1."""
    from datetime import time, timedelta

    from apps.bookings import services
    from apps.bookings.availability import local_today
    from apps.dorms.models import TimeSlot

    LedgerEntry.objects.create(resident=resident, kind="credit", amount=200, note="Cash")
    second = TimeSlot.objects.create(dormitory=dormitory, start_time=time(10, 0))
    day = local_today(dormitory) + timedelta(days=2)
    return services.book_slots(resident, machine, day, [slot, second])


def lines(client):
    return list(client.get(BALANCE).context["page"])


def test_a_booking_is_one_line(client, resident, four_hours):
    client.force_login(resident.user)
    client.cookies["django_language"] = "en"
    page = lines(client)
    assert [line.amount for line in page] == [-100, 200]
    booking_line = page[0]
    assert booking_line.is_grouped and len(booking_line.entries) == 2
    assert booking_line.machine.number == 1
    html = client.get(BALANCE).content.decode()
    assert "Machine 1" in html and "08:00–12:00" in html
    assert "−100 RUB" in html
    # The ledger itself still has one entry per slot.
    assert LedgerEntry.objects.filter(resident=resident, kind="booking").count() == 2


def test_refunds_are_grouped_and_lines_add_up(client, resident, four_hours):
    from apps.bookings import services

    services.cancel_group(four_hours[0].group_id, actor=resident.user)
    client.force_login(resident.user)
    page = lines(client)
    assert [line.amount for line in page] == [100, -100, 200]
    assert sum(line.amount for line in page) == LedgerEntry.objects.balance(resident)


def test_partial_cancellation_gets_its_own_refund_line(client, resident, four_hours):
    from apps.bookings import services

    services.cancel_booking(four_hours[1], actor=resident.user)
    client.force_login(resident.user)
    page = lines(client)
    assert [line.amount for line in page] == [50, -100, 200]
    assert page[0].starts_at == four_hours[1].starts_at


def test_balance_page_shows_own_name_and_room(client, resident, other_resident, history):
    client.force_login(resident.user)
    client.cookies["django_language"] = "en"
    html = client.get(BALANCE).content.decode()
    assert resident.full_name in html and f"room {resident.room}" in html
    assert other_resident.full_name not in html
