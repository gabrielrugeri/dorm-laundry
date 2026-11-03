"""Opening balances from the residents import: the money a resident had
before the app, entered once. Every name here is fake."""

from datetime import timedelta

import pytest
from django.db import IntegrityError, transaction
from django.urls import reverse
from django.utils import timezone

from apps.accounts import roles
from apps.accounts.models import Resident
from apps.accounts.tests.test_initial_pins import import_rows, upload
from apps.audit.models import AuditEvent
from apps.keylog.tests.test_services import make_staff
from apps.ledger import services
from apps.ledger.models import LedgerEntry


@pytest.fixture
def boss(dormitory):
    return make_staff(dormitory, "boss", role=roles.ADMIN)


@pytest.fixture
def boss_client(client, boss):
    client.force_login(boss)
    client.cookies["django_language"] = "en"
    return client


def test_positive_and_negative_opening_balances(boss_client):
    import_rows(
        boss_client,
        ("S1", "Ivan Testov", "101", "", "150"),
        ("S2", "Anna Testova", "102", "", "-80"),
        ("S3", "Petr Testov", "103", "", ""),
        ("S4", "Olga Testova", "104", "", "1 200 ₽"),
    )
    balances = {r.student_code: LedgerEntry.objects.balance(r) for r in Resident.objects.all()}
    assert balances == {"S1": 150, "S2": -80, "S3": 0, "S4": 1200}
    entry = LedgerEntry.objects.get(resident__student_code="S2")
    assert entry.kind == "opening" and entry.label == "opening balance"
    assert AuditEvent.objects.filter(action="ledger.opening").count() == 3


@pytest.mark.parametrize("value", ["150,50", "abc", "999999", "1e3"])
def test_bad_opening_balances_are_row_errors(boss_client, value):
    result = upload(boss_client, ("S1", "Ivan Testov", "101", "", value)).context["result"]
    assert result.rows[0].status == "error"


def test_reimport_never_applies_it_twice(boss_client):
    import_rows(boss_client, ("S1", "Ivan Testov", "101", "", "150"))
    preview = upload(boss_client, ("S1", "Ivan Testov", "101", "", "150"))
    assert preview.context["result"].opening_rows == []
    assert preview.context["result"].rows[0].opening_already
    import_rows(boss_client, ("S1", "Ivan Testov", "101", "", "300"))
    resident = Resident.objects.get(student_code="S1")
    assert LedgerEntry.objects.balance(resident) == 150


def test_the_database_refuses_a_second_opening_balance(resident, boss):
    services.set_opening_balance(actor=boss, resident=resident, amount=100)
    with pytest.raises(IntegrityError), transaction.atomic():
        LedgerEntry.objects.create(resident=resident, kind="opening", amount=50)
    with pytest.raises(IntegrityError), transaction.atomic():
        LedgerEntry.objects.create(resident=resident, kind="opening", amount=0)


def test_existing_residents_get_one_too(boss_client, resident):
    import_rows(
        boss_client,
        (resident.student_code, resident.full_name, resident.room, "", "-40"),
    )
    assert LedgerEntry.objects.balance(resident) == -40


def test_preview_shows_the_opening_balances(boss_client):
    html = upload(
        boss_client,
        ("S1", "Ivan Testov", "101", "", "150"),
        ("S2", "Anna Testova", "102", "", "-80"),
    ).content.decode()
    assert "Opening balances for 2 residents" in html
    assert "+70" in html.replace("\xa0", " ")  # 150 − 80


def test_the_credit_limit_applies_after_an_old_debt(resident, boss, machine, slot):
    from apps.bookings import services as bookings
    from apps.bookings.availability import local_today

    services.set_opening_balance(actor=boss, resident=resident, amount=-100)  # the limit
    with pytest.raises(bookings.BookingError):
        bookings.book_slots(
            resident, machine, local_today(resident.dormitory) + timedelta(days=1), [slot]
        )


def test_the_money_report_keeps_opening_balances_apart(boss_client, boss, resident):
    services.add_manual_entry(actor=boss, resident=resident, kind="credit", amount=200)
    services.set_opening_balance(actor=boss, resident=resident, amount=-80)
    today = timezone.localdate()
    response = boss_client.get(
        reverse("manage:receipt_report"),
        {"from": today.isoformat(), "to": today.isoformat(), "format": "csv"},
    )
    header, row = response.content.decode("utf-8-sig").splitlines()[:2]
    columns = header.split(";")
    values = dict(zip(columns, row.split(";"), strict=False))
    assert values["Opening balances"] == "-80"
    assert values["Payments recorded by admins"] == "200"
