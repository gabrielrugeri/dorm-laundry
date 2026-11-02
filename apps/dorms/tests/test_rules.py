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
    ) == (100, 2000, 5000, 3, 10)
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
