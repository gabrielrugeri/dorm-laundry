"""The admin dashboard: numbers, chart data and geometry. Every name is fake."""

from datetime import date, datetime, time, timedelta

import pytest
from django.urls import reverse

from apps.accounts import roles
from apps.bookings.models import Booking
from apps.dorms.models import Machine, TimeSlot
from apps.keylog.tests.test_services import make_staff
from apps.ledger.models import LedgerEntry
from apps.manage import charts, dashboard

TODAY = date(2026, 10, 21)  # a Wednesday
DASHBOARD = reverse("manage:dashboard")


def at(day, hour, dormitory):
    return datetime.combine(day, time(hour), tzinfo=dormitory.tzinfo)


def entry(resident, kind, amount, when, **extra):
    created = LedgerEntry.objects.create(resident=resident, kind=kind, amount=amount, **extra)
    # created_at is set automatically; the test moves it to `when`.
    LedgerEntry.objects.filter(pk=created.pk).update(created_at=when)
    return created


def booking(resident, machine, slot, day, status="active"):
    made = Booking(resident=resident, machine=machine, slot=slot, date=day, price_rub=50)
    made.status = status
    if status != "active":
        from django.utils import timezone

        made.cancelled_at = timezone.now()
    made.save()
    return made


# --- Numbers ---------------------------------------------------------------------------


def test_money_received_counts_payments_minus_voided(resident, other_resident, dormitory):
    entry(resident, "credit", 300, at(TODAY, 10, dormitory))  # this month
    entry(resident, "credit", 200, at(date(2026, 9, 30), 23, dormitory))  # last month
    entry(other_resident, "adjustment", 500, at(TODAY, 11, dormitory))  # not money received
    tiles = dashboard.tiles(dormitory, TODAY)
    assert (tiles.received_this_month, tiles.received_last_month) == (300, 200)


def test_debt_and_debtors(resident, other_resident, dormitory):
    entry(resident, "adjustment", -80, at(TODAY, 9, dormitory))
    entry(other_resident, "adjustment", 40, at(TODAY, 9, dormitory))
    tiles = dashboard.tiles(dormitory, TODAY)
    assert (tiles.debt_total, tiles.debtors) == (80, 1)


def test_occupancy_this_week(resident, dormitory, machine, slot):
    Machine.objects.create(dormitory=dormitory, number=2)
    monday = TODAY - timedelta(days=TODAY.weekday())
    booking(resident, machine, slot, monday)
    booking(resident, machine, slot, monday + timedelta(days=1), status="cancelled")
    # 2 machines × 1 slot × 7 days = 14 machine-slots; 1 booked.
    assert dashboard.tiles(dormitory, TODAY).occupancy_this_week == pytest.approx(1 / 14)


def test_heatmap_by_weekday_and_slot(resident, dormitory, machine, slot):
    late = TimeSlot.objects.create(dormitory=dormitory, start_time=time(22, 0))
    monday = dashboard.history_start(TODAY, weeks=2)
    booking(resident, machine, late, monday)
    heat = dashboard.heatmap(dormitory, TODAY, weeks=2)
    assert [s.start_time for s in heat["slots"]] == [time(8, 0), time(22, 0)]
    monday_row = heat["rows"][0][1]
    assert monday_row == [0.0, 0.5]  # two Mondays, one machine: 1 of 2 booked


def test_received_per_week(resident, dormitory):
    first = dashboard.history_start(TODAY, weeks=3)
    entry(resident, "credit", 100, at(first, 12, dormitory))
    entry(resident, "credit", 50, at(first + timedelta(days=8), 12, dormitory))
    assert [amount for _monday, amount in dashboard.received_per_week(dormitory, TODAY, 3)] == [
        100,
        50,
        0,
    ]


def test_usage_per_machine(resident, dormitory, machine, slot):
    second = Machine.objects.create(dormitory=dormitory, number=2)
    day = TODAY - timedelta(days=1)
    booking(resident, machine, slot, day)
    assert [(m.number, n) for m, n in dashboard.usage_per_machine(dormitory, TODAY)] == [
        (1, 1),
        (second.number, 0),
    ]


# --- Geometry ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "nice"), [(0, 1), (7, 10), (130, 200), (2400, 2500), (4100, 5000)]
)
def test_nice_axis_maximum(value, nice):
    assert charts.nice_max(value) == nice


def test_bars_are_rounded_at_the_top_and_zero_has_no_shape():
    chart = charts.column_chart([("a", 100), ("b", 0)])
    assert chart["bars"][0]["path"].startswith("M") and "Q" in chart["bars"][0]["path"]
    assert chart["bars"][1]["path"] == ""


@pytest.mark.parametrize(("share", "level"), [(None, 0), (0, 0), (0.05, 1), (0.5, 3), (1, 5)])
def test_heat_levels(share, level):
    assert charts.heat_level(share) == level


# --- Page ---------------------------------------------------------------------------------


def test_dashboard_for_admins_only(client, dormitory, resident):
    client.force_login(resident.user)
    assert client.get(DASHBOARD).status_code == 403
    client.force_login(make_staff(dormitory, "keys", role=roles.MANAGER))
    assert client.get(DASHBOARD).status_code == 403


def test_dashboard_page(client, dormitory, resident, machine, slot):
    client.force_login(make_staff(dormitory, "boss", role=roles.ADMIN))
    client.cookies["django_language"] = "en"
    html = client.get(DASHBOARD).content.decode()
    for words in ("Received this month", "When machines are busy", "Money received per week"):
        assert words in html
    assert "<svg" in html and "Show as a table" in html
    assert 'href="http' not in html  # nothing loaded from elsewhere
