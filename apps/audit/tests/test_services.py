"""Tests for the audit log core. Every name here is fake."""

import pytest
from django.contrib.auth.models import AnonymousUser

from apps.accounts.models import User
from apps.audit.models import AuditEvent
from apps.audit.services import record, snapshot


def test_record_fills_target_and_dormitory(resident, admin_user):
    before = snapshot(resident)
    resident.room = "305"
    resident.save()
    event = record(
        actor=admin_user,
        action="admin.change",
        target=resident,
        before=before,
        after=snapshot(resident),
        reason="moved",
    )
    assert event.target_type == "accounts.Resident"
    assert event.target_id == str(resident.pk)
    assert event.dormitory == resident.dormitory
    assert event.changes == [("room", "101", "305")]


def test_snapshot_never_contains_passwords(resident):
    data = snapshot(resident.user)
    assert "password" not in data
    assert data["username"] == resident.user.username


def test_snapshot_is_json_safe(make_booking):
    data = snapshot(make_booking())
    assert data["date"] == "2026-10-14"
    assert isinstance(data["group_id"], str)


def test_events_are_append_only(admin_user):
    event = record(actor=admin_user, action="admin.add")
    event.reason = "edited"
    with pytest.raises(ValueError):
        event.save()
    with pytest.raises(ValueError):
        event.delete()
    assert AuditEvent.objects.get().reason == ""


def test_anonymous_or_missing_actor_is_system(db):
    assert record(actor=AnonymousUser(), action="admin.add").actor is None
    assert record(actor=None, action="admin.add").actor is None


def test_staff_user_dormitory_is_found(dormitory):
    from apps.accounts.models import StaffProfile

    user = User.objects.create_user(username="boss")
    StaffProfile.objects.create(user=user, dormitory=dormitory)
    assert record(actor=user, action="admin.change", target=user).dormitory == dormitory
