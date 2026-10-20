"""The change history shows plain words, never field names, codes, ids,
JSON or UTC times. Every name here is fake."""

from datetime import timedelta

from django.utils import translation

from apps.accounts import roles
from apps.audit.display import describe_changes
from apps.audit.models import AuditEvent
from apps.audit.services import record, snapshot
from apps.bookings import services
from apps.bookings.availability import local_today
from apps.keylog.tests.test_services import make_staff
from apps.ledger.models import LedgerEntry


def test_staff_cancellation_in_plain_english(resident, machine, slot, dormitory):
    LedgerEntry.objects.create(resident=resident, kind="credit", amount=50, note="x")
    day = local_today(dormitory) + timedelta(days=2)
    booking = services.book_slots(resident, machine, day, [slot])[0]
    boss = make_staff(dormitory, "boss", role=roles.ADMIN)
    services.cancel_booking(booking, actor=boss, reason="Pipe repair", full_refund=True)

    with translation.override("en"):
        rows = {label: (old, new) for label, old, new in describe_changes(AuditEvent.objects.get())}
    assert rows["Status"] == ("active", "cancelled by the administration")
    assert rows["Reason for cancellation"] == ("—", "Pipe repair")
    assert rows["Refunded"] == ("—", "50 RUB")
    assert rows["Full refund"] == ("—", "Yes")
    old, new = rows["Cancelled at"]
    assert old == "—" and "+00:00" not in new and ":" in new  # local time, not ISO/UTC


def test_internal_fields_and_ids_are_left_out(resident):
    boss_dorm = resident.dormitory
    boss = make_staff(boss_dorm, "boss", role=roles.ADMIN)
    before = snapshot(resident)
    resident.room = "305"
    resident.save()
    event = record(
        actor=boss,
        action="resident.update",
        target=resident,
        before=before,
        after={**snapshot(resident), "id": 99, "user": 7, "mystery_internal": 1},
    )
    with translation.override("ru"):
        rows = describe_changes(event)
    assert rows == [("Комната", "101", "305")]


def test_roles_are_named(resident):
    boss = make_staff(resident.dormitory, "boss", role=roles.ADMIN)
    event = record(
        actor=boss,
        action="admin.change",
        target=resident.user,
        before={"groups": ["resident"]},
        after={"groups": ["manager"]},
    )
    with translation.override("en"):
        assert describe_changes(event) == [("Role", "Resident", "Key manager")]


def test_history_page_shows_no_technical_values(client, resident, machine, slot, dormitory):
    LedgerEntry.objects.create(resident=resident, kind="credit", amount=50, note="x")
    day = local_today(dormitory) + timedelta(days=2)
    booking = services.book_slots(resident, machine, day, [slot])[0]
    boss = make_staff(dormitory, "boss", role=roles.ADMIN)
    services.cancel_booking(booking, actor=boss, reason="Pipe repair")
    client.force_login(boss)
    html = client.get("/manage/history/").content.decode()
    for raw in ("cancelled_by_admin", "cancel_reason", "refund_rub", "+00:00", "True", "group_id"):
        assert raw not in html, raw
    assert "Pipe repair" in html
