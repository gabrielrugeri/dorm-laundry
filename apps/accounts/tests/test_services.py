"""Resident management services. Every name and code here is fake."""

import pytest

from apps.accounts import roles, services
from apps.accounts.models import Resident, User
from apps.audit.models import AuditEvent
from apps.audit.services import record, snapshot
from apps.keylog.tests.test_services import make_staff
from apps.ledger.models import LedgerEntry


@pytest.fixture
def boss(dormitory):
    return make_staff(dormitory, "boss", role=roles.ADMIN)


def actions():
    return list(AuditEvent.objects.order_by("id").values_list("action", flat=True))


def test_create_resident(boss, dormitory):
    resident = services.create_resident(
        actor=boss, dormitory=dormitory, full_name=" Olga Primerova ", room="214", student_code="S9"
    )
    assert resident.full_name == "Olga Primerova"
    assert not resident.user.has_usable_password()
    assert roles.has_role(resident.user, roles.RESIDENT)
    assert "S9" not in resident.user.username  # internal username never holds the code
    assert actions() == ["resident.create"]


def test_update_resident_records_changes(boss, resident):
    services.update_resident(
        actor=boss, resident=resident, room="305", full_name=resident.full_name
    )
    event = AuditEvent.objects.get()
    assert event.action == "resident.update"
    assert event.changes == [("room", "101", "305")]
    services.update_resident(actor=boss, resident=resident, room="305")
    assert AuditEvent.objects.count() == 1  # no change, no event


def test_deactivate_and_reactivate(boss, resident):
    services.deactivate(actor=boss, resident=resident)
    resident.user.refresh_from_db()
    assert not resident.user.is_active
    services.reactivate(actor=boss, resident=resident)
    resident.user.refresh_from_db()
    assert resident.user.is_active
    assert actions() == ["resident.deactivate", "resident.reactivate"]


def test_debt_must_be_confirmed(boss, resident):
    LedgerEntry.objects.create(resident=resident, kind="adjustment", amount=-120, note="x")
    with pytest.raises(services.DebtNotConfirmed):
        services.deactivate(actor=boss, resident=resident)
    with pytest.raises(services.DebtNotConfirmed):
        services.anonymize(actor=boss, resident=resident)
    resident.user.refresh_from_db()
    assert resident.user.is_active and not AuditEvent.objects.exists()

    services.deactivate(actor=boss, resident=resident, confirm_debt=True)
    event = AuditEvent.objects.get()
    assert event.after == {"balance": -120, "debt_confirmed": True}


def test_anonymize_erases_personal_data_everywhere(boss, resident, make_booking):
    make_booking()
    LedgerEntry.objects.create(resident=resident, kind="credit", amount=100, note="cash")
    before = snapshot(resident)
    resident.room = "999"
    resident.save()
    record(
        actor=boss,
        action="resident.update",
        target=resident,
        before=before,
        after=snapshot(resident),
    )
    record(actor=boss, action="admin.change", target=resident.user, after=snapshot(resident.user))

    services.anonymize(actor=boss, resident=resident)

    resident.refresh_from_db()
    assert resident.is_anonymized and resident.full_name == "" and resident.room == ""
    assert "S0001" not in resident.student_code
    from django.utils import translation

    with translation.override("en"):
        assert str(resident) == "Former resident"
    user = User.objects.get(pk=resident.user_id)
    assert not user.is_active and not user.has_usable_password()
    assert "S0001" not in user.username
    # Money history stays.
    assert LedgerEntry.objects.balance(resident) == 100
    assert resident.bookings.count() == 1
    # Old audit snapshots no longer contain the name, room, code or username.
    dump = str(list(AuditEvent.objects.values("before", "after", "target_repr")))
    for secret in ("Ivan Testov", "999", "S0001", "test-S0001"):
        assert secret not in dump
    assert actions()[-1] == "resident.anonymize"


def test_cannot_anonymize_twice_or_edit_after(boss, resident):
    services.anonymize(actor=boss, resident=resident)
    with pytest.raises(services.AlreadyErased):
        services.anonymize(actor=boss, resident=resident)
    with pytest.raises(services.AlreadyErased):
        services.update_resident(actor=boss, resident=resident, room="1")
    with pytest.raises(services.AlreadyErased):
        services.reactivate(actor=boss, resident=resident)


def test_delete_only_without_history(boss, resident, make_booking):
    fresh = services.create_resident(
        actor=boss, dormitory=resident.dormitory, full_name="Typo", room="1", student_code="X1"
    )
    services.delete_resident(actor=boss, resident=fresh)
    assert not Resident.objects.filter(pk=fresh.pk).exists()
    assert actions()[-1] == "resident.delete"

    make_booking()
    with pytest.raises(services.HasHistory):
        services.delete_resident(actor=boss, resident=resident)
    assert Resident.objects.filter(pk=resident.pk).exists()


def test_debt_since(resident):
    from datetime import timedelta

    from django.utils import timezone

    assert LedgerEntry.objects.debt_since(resident) is None
    LedgerEntry.objects.create(resident=resident, kind="adjustment", amount=-50, note="a")
    first = LedgerEntry.objects.debt_since(resident)
    assert first is not None
    LedgerEntry.objects.create(resident=resident, kind="credit", amount=100, note="b")
    assert LedgerEntry.objects.debt_since(resident) is None
    entry = LedgerEntry.objects.create(resident=resident, kind="adjustment", amount=-80, note="c")
    assert LedgerEntry.objects.debt_since(resident) == entry.created_at
    assert entry.created_at <= timezone.now() + timedelta(seconds=1)
