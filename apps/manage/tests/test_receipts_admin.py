"""Stage 5: voiding receipts, flags, the receipts screens and the money
report. Every name here is fake."""

from datetime import UTC, date, datetime, timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.urls import reverse

from apps.accounts import roles
from apps.audit.models import AuditEvent
from apps.keylog.tests.test_services import make_staff
from apps.ledger.models import LedgerEntry
from apps.receipts import services
from apps.receipts.flags import flags_for
from apps.receipts.models import Receipt

NOW = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)
LIST = reverse("manage:receipts")
REPORT = reverse("manage:receipt_report")


def send(resident, amount=100, tag="x", now=NOW):
    data = b"%PDF-1.4\n% fake " + f"{resident.pk}-{amount}-{tag}".encode() + b"\n%%EOF\n"
    return services.submit_receipt(
        resident=resident, amount=amount, upload=SimpleUploadedFile("r.pdf", data), now=now
    )


@pytest.fixture
def boss(dormitory):
    return make_staff(dormitory, "boss", role=roles.ADMIN)


@pytest.fixture
def boss_client(client, boss):
    client.force_login(boss)
    client.cookies["django_language"] = "en"
    return client


# --- Voiding ---------------------------------------------------------------------------


def test_void_takes_the_money_back(resident, boss):
    receipt = send(resident, 300)
    services.void_receipt(receipt=receipt, actor=boss, reason="Not on the bank statement")
    receipt.refresh_from_db()
    assert receipt.status == Receipt.Status.VOIDED and receipt.voided_by == boss
    reversal = LedgerEntry.objects.get(kind=LedgerEntry.Kind.REVERSAL)
    assert (reversal.amount, reversal.receipt, reversal.note) == (
        -300,
        receipt,
        "Not on the bank statement",
    )
    assert LedgerEntry.objects.balance(resident) == 0
    assert AuditEvent.objects.get(action="receipt.void").reason == "Not on the bank statement"


def test_void_twice_changes_nothing(resident, boss):
    receipt = send(resident, 300)
    services.void_receipt(receipt=receipt, actor=boss, reason="Wrong")
    services.void_receipt(receipt=receipt, actor=boss, reason="Again")
    assert LedgerEntry.objects.filter(kind=LedgerEntry.Kind.REVERSAL).count() == 1
    assert AuditEvent.objects.filter(action="receipt.void").count() == 1


def test_void_may_leave_a_debt_and_the_credit_limit_applies(resident, boss, machine, slot):
    from apps.bookings import services as booking_services
    from apps.bookings.availability import local_today

    receipt = send(resident, 200)
    day = local_today(resident.dormitory) + timedelta(days=2)
    booking_services.book_slots(resident, machine, day, [slot])  # 200 - 50 = 150
    services.void_receipt(receipt=receipt, actor=boss, reason="Fake")
    assert LedgerEntry.objects.balance(resident) == -50  # within the 100 RUB limit


def test_void_needs_a_reason_and_an_admin_of_the_dormitory(
    resident, boss, dormitory, other_dormitory
):
    receipt = send(resident)
    with pytest.raises(ValueError):
        services.void_receipt(receipt=receipt, actor=boss, reason=" ")
    with pytest.raises(services.NotAllowed):
        services.void_receipt(
            receipt=receipt, actor=make_staff(dormitory, "keys", role=roles.MANAGER), reason="x"
        )
    with pytest.raises(services.NotAllowed):
        services.void_receipt(
            receipt=receipt,
            actor=make_staff(other_dormitory, "stranger", role=roles.ADMIN),
            reason="x",
        )
    assert Receipt.objects.get().status == Receipt.Status.CREDITED


def test_voided_receipts_free_the_30_day_cap(resident, boss):
    from apps.dorms.models import GlobalSettings

    GlobalSettings.objects.filter(pk=1).update(max_uploads_per_day=20)
    receipts = [send(resident, 2000, tag=str(n)) for n in range(2)]
    send(resident, 1000, tag="c")
    with pytest.raises(services.ReceiptRefused):
        send(resident, 500, tag="d")
    services.void_receipt(receipt=receipts[0], actor=boss, reason="Duplicate payment")
    send(resident, 500, tag="d")


def test_a_reversal_needs_a_receipt_and_happens_once(resident, boss):
    with pytest.raises(IntegrityError), transaction.atomic():
        LedgerEntry.objects.create(resident=resident, kind="reversal", amount=-10)
    receipt = send(resident)
    services.void_receipt(receipt=receipt, actor=boss, reason="x")
    with pytest.raises(IntegrityError), transaction.atomic():
        LedgerEntry.objects.create(resident=resident, kind="reversal", amount=-100, receipt=receipt)


def test_resident_sees_the_voided_receipt_in_their_balance(client, resident, boss):
    services.void_receipt(receipt=send(resident, 150), actor=boss, reason="Not received")
    client.force_login(resident.user)
    client.cookies["django_language"] = "en"
    html = client.get(reverse("ledger:balance")).content.decode()
    assert "Receipt voided" in html and "−150 RUB" in html and "Not received" in html


# --- Flags --------------------------------------------------------------------------------


def codes(receipt):
    return [code for code, _label in flags_for(receipt)]


def test_flags_explain_what_to_check(resident, boss):
    from apps.dorms.models import GlobalSettings

    GlobalSettings.objects.filter(pk=1).update(max_uploads_per_day=20, max_credit_per_30_days=4000)
    first = send(resident, 1800, tag="a")  # 80% of the 2000 RUB maximum
    assert ("large", "Large amount") in [(c, str(label)) for c, label in flags_for(first)]
    second = send(resident, 1800, tag="b", now=NOW + timedelta(hours=3))
    assert "repeat" in codes(second)
    assert "near_cap" in codes(second)  # 3600 of 4000 in 30 days
    services.void_receipt(receipt=first, actor=boss, reason="x")
    third = send(resident, 100, tag="c", now=NOW + timedelta(days=40))
    assert "earlier_voids" in codes(third)
    assert "repeat" not in codes(third) and "large" not in codes(third)


def test_spent_right_after_and_debt_flags(resident, machine, slot, dormitory):
    from django.utils import timezone

    from apps.bookings import services as booking_services
    from apps.bookings.availability import local_today
    from apps.dorms.models import TimeSlot

    slot_10 = TimeSlot.objects.create(
        dormitory=dormitory, start_time=slot.start_time.replace(hour=10)
    )
    receipt = send(resident, 100, now=timezone.now())
    day = local_today(dormitory) + timedelta(days=2)
    booking_services.book_machines(resident, [machine], day, [slot, slot_10])  # 100 at once
    assert "spent_quickly" in codes(receipt)
    assert "negative_balance" not in codes(receipt)  # 100 - 100 = 0
    booking_services.book_slots(resident, machine, day + timedelta(days=1), [slot])
    assert "negative_balance" in codes(receipt)  # still allowed: within the credit limit


# --- Screens ------------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["receipts", "receipt_report"])
def test_admins_only(client, dormitory, resident, name):
    url = reverse(f"manage:{name}")
    client.force_login(resident.user)
    assert client.get(url).status_code == 403
    client.force_login(make_staff(dormitory, "keys", role=roles.MANAGER))
    assert client.get(url).status_code == 403


def test_list_and_detail(boss_client, resident, other_dormitory):
    from conftest import make_resident

    receipt = send(resident, 1900)
    elsewhere = send(make_resident(other_dormitory, "Z1", name="Elsewhere"), 100)
    html = boss_client.get(LIST).content.decode()
    assert resident.full_name in html and "Large amount" in html
    assert "Elsewhere" not in html
    assert [r.pk for r, _f in boss_client.get(LIST, {"status": "voided"}).context["page"]] == []
    detail = boss_client.get(reverse("manage:receipt", kwargs={"pk": receipt.pk}))
    assert detail.status_code == 200
    assert reverse("receipts:file", kwargs={"pk": receipt.pk}) in detail.content.decode()
    other = reverse("manage:receipt", kwargs={"pk": elsewhere.pk})
    assert boss_client.get(other).status_code == 404


def test_void_screen_needs_reason_and_tick(boss_client, resident):
    receipt = send(resident, 300)
    url = reverse("manage:receipt_void", kwargs={"pk": receipt.pk})
    page = boss_client.get(url)
    assert "300 RUB will be taken back" in page.content.decode()
    page = boss_client.post(url, {"reason": "No such payment"})
    assert page.context["form"].errors["confirm"]
    boss_client.post(url, {"reason": "No such payment", "confirm": "on"})
    receipt.refresh_from_db()
    assert receipt.status == Receipt.Status.VOIDED
    # A voided receipt has no void button any more.
    detail = boss_client.get(reverse("manage:receipt", kwargs={"pk": receipt.pk}))
    assert url not in detail.content.decode()


def test_admin_navigation_has_receipts(boss_client):
    assert f'href="{LIST}"' in boss_client.get(reverse("manage:residents")).content.decode()


# --- Money report -------------------------------------------------------------------------


@pytest.fixture
def october(resident, other_resident, boss):
    """Money in October 2026 in every column."""
    from apps.ledger.services import add_manual_entry

    kept = send(resident, 300, tag="kept")
    voided = send(other_resident, 200, tag="void")
    services.void_receipt(receipt=voided, actor=boss, reason="Fake")
    add_manual_entry(actor=boss, resident=resident, kind="credit", amount=500, note="Cash")
    add_manual_entry(actor=boss, resident=resident, kind="adjustment", amount=-40, note="Fix")
    return kept


def test_report_keeps_each_kind_in_its_own_column(boss_client, october):
    today = date.today()
    response = boss_client.get(
        REPORT, {"from": "2026-01-01", "to": today.isoformat(), "by": "month"}
    )
    totals, total = response.context["totals"]
    columns = [key for key, _label in response.context["columns"]]
    by_column = dict(zip(columns, totals, strict=True))
    assert by_column["receipts"] == 500  # 300 + 200 credited by receipts
    assert by_column["voided"] == -200
    assert by_column["payments"] == 500
    assert by_column["corrections"] == -40
    assert total == 760


def test_report_by_resident_and_csv(boss_client, october, resident):
    today = date.today().isoformat()
    by_resident = boss_client.get(REPORT, {"from": "2026-01-01", "to": today, "by": "resident"})
    labels = [label for label, _values, _total in by_resident.context["rows"]]
    assert f"{resident.full_name} ({resident.room})" in labels
    csv_response = boss_client.get(
        REPORT, {"from": "2026-01-01", "to": today, "by": "day", "format": "csv"}
    )
    assert csv_response["Content-Type"].startswith("text/csv")
    body = csv_response.content.decode("utf-8-sig")
    assert body.splitlines()[0].startswith("Period;Receipts;Voided receipts")
    assert body.splitlines()[-1].endswith(";760")
