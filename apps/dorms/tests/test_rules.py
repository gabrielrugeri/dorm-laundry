"""Money and upload rules: defaults, bounds, big changes and the history."""

import pytest

from apps.accounts import roles
from apps.audit.models import AuditEvent
from apps.dorms import rules
from apps.dorms.models import GlobalSettings
from apps.keylog.tests.test_services import make_staff


def values(**changes):
    base = {name: getattr(rules.current(), name) for name in rules.FIELDS}
    return {**base, **changes}


def test_defaults_are_the_approved_ones(db):
    current = rules.current()
    assert (
        current.credit_limit,
        current.max_receipt_amount,
        current.max_credit_per_30_days,
        current.max_uploads_per_day,
        current.max_upload_mb,
    ) == (100, 600, 1500, 3, 10)
    assert GlobalSettings.objects.count() == 1


def test_credit_limit_for_reads_the_rule(resident):
    assert rules.credit_limit_for(resident) == 100
    GlobalSettings.objects.filter(pk=1).update(credit_limit=None)
    assert rules.credit_limit_for(resident) is None


@pytest.mark.parametrize(
    ("old", "new", "big"),
    [
        (100, 100, False),
        (100, 1000, False),
        (100, 1001, True),
        (100, 10, False),
        (100, 9, True),
        (100, 0, True),
        (0, 50, True),
        (100, None, True),
        (None, 100, True),
    ],
)
def test_big_changes(old, new, big):
    assert rules.is_big_change(old, new) is big


def test_change_is_recorded_with_old_and_new_values(dormitory):
    boss = make_staff(dormitory, "boss", role=roles.ADMIN)
    rules.change_settings(actor=boss, values=values(credit_limit=200), reason="New semester")
    assert rules.current().credit_limit == 200
    event = AuditEvent.objects.get(action="settings.change")
    assert event.before["credit_limit"] == 100 and event.after["credit_limit"] == 200
    assert event.reason == "New semester"
    assert event.dormitory == dormitory


@pytest.mark.parametrize(
    "bad",
    [
        {"credit_limit": 10_001},
        {"max_receipt_amount": 10},
        {"max_uploads_per_day": 0},
        {"max_upload_mb": 999},  # above the server's hard limit
        {"max_receipt_amount": 3000, "max_credit_per_30_days": 2000},
    ],
    ids=["limit", "receipt", "uploads", "file-size", "30-days-below-receipt"],
)
def test_values_outside_bounds_are_refused(dormitory, bad):
    boss = make_staff(dormitory, "boss", role=roles.ADMIN)
    with pytest.raises(rules.InvalidRules):
        rules.change_settings(actor=boss, values=values(**bad), reason="x")
    assert not AuditEvent.objects.exists()


def test_reason_is_required(dormitory):
    boss = make_staff(dormitory, "boss", role=roles.ADMIN)
    with pytest.raises(rules.InvalidRules):
        rules.change_settings(actor=boss, values=values(credit_limit=50), reason="  ")
    assert rules.current().credit_limit == 100


# --- Lower receipt defaults (migration 0006) ---------------------------------------


def _migration():
    import importlib

    return importlib.import_module("apps.dorms.migrations.0006_receipt_limit_defaults")


def _run_migration():
    from django.apps import apps

    _migration().lower_the_defaults(apps, None)


def test_migration_lowers_the_old_defaults_and_records_it(resident):
    GlobalSettings.objects.filter(pk=1).update(max_receipt_amount=2000, max_credit_per_30_days=5000)
    _run_migration()
    current = rules.current()
    assert (current.max_receipt_amount, current.max_credit_per_30_days) == (600, 1500)
    event = AuditEvent.objects.get(action="settings.change")
    assert event.actor is None and event.reason
    assert event.before["max_receipt_amount"] == 2000
    assert event.after["max_credit_per_30_days"] == 1500


@pytest.mark.parametrize(
    "chosen", [(1000, 5000), (2000, 8000)], ids=["receipt-changed", "30-days-changed"]
)
def test_migration_keeps_values_an_admin_chose(resident, chosen):
    receipt, month = chosen
    GlobalSettings.objects.filter(pk=1).update(
        max_receipt_amount=receipt, max_credit_per_30_days=month
    )
    _run_migration()
    current = rules.current()
    assert (current.max_receipt_amount, current.max_credit_per_30_days) == chosen
    assert not AuditEvent.objects.exists()


# --- Largest receipt file: superusers only ------------------------------------------


def test_admins_change_only_their_rules_on_manage(dormitory):
    assert "max_upload_mb" not in rules.FIELDS
    assert "max_upload_mb" in rules.SUPERUSER_FIELDS


def test_upload_limit_never_above_the_server_limit(db, settings):
    GlobalSettings.objects.filter(pk=1).update(max_upload_mb=10)
    settings.MAX_UPLOAD_BYTES_HARD = 4 * 1024 * 1024  # lowered after the rule was saved
    assert rules.max_upload_bytes() == 4 * 1024 * 1024


ADMIN_URL = "/admin/dorms/globalsettings/1/change/"


def test_superuser_changes_the_file_size_in_django_admin_with_a_reason(client, admin_user):
    client.force_login(admin_user)
    data = {"max_upload_mb": 5, "reason": "Phones send smaller pictures now"}
    response = client.post(ADMIN_URL, data)
    assert response.status_code == 302, response.content.decode()[:2000]
    assert rules.current().max_upload_mb == 5
    event = AuditEvent.objects.get(action="settings.change")
    assert event.actor == admin_user
    assert event.reason == "Phones send smaller pictures now"
    assert (event.before["max_upload_mb"], event.after["max_upload_mb"]) == (10, 5)


@pytest.mark.parametrize(
    "data",
    [{"max_upload_mb": 999, "reason": "x"}, {"max_upload_mb": 5, "reason": ""}],
    ids=["above-server-limit", "no-reason"],
)
def test_django_admin_refuses_bad_file_sizes(client, admin_user, data):
    client.force_login(admin_user)
    assert client.post(ADMIN_URL, data).status_code == 200  # the form again, with errors
    assert rules.current().max_upload_mb == 10
    assert not AuditEvent.objects.exists()


def test_django_admin_cannot_change_the_money_rules(client, admin_user):
    client.force_login(admin_user)
    client.post(ADMIN_URL, {"max_upload_mb": 10, "max_receipt_amount": 99999, "reason": "sneaky"})
    assert rules.current().max_receipt_amount == 600
