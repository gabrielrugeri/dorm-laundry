"""Django admin cannot bypass the booking service, and every edit is audited.
Every name here is fake."""

from datetime import timedelta

import pytest
from django.contrib.auth.models import Group
from django.urls import reverse

from apps.accounts import roles
from apps.accounts.models import StaffProfile, User
from apps.audit.models import AuditEvent
from apps.bookings import services
from apps.bookings.availability import local_today
from apps.bookings.models import Booking
from apps.ledger.models import LedgerEntry

CHANGELIST = reverse("admin:bookings_booking_changelist")


@pytest.fixture
def boss(dormitory):
    """An admin of the test dormitory who can use Django admin."""
    user = User.objects.create_user(username="boss", password="x", is_staff=True, is_superuser=True)
    user.groups.add(Group.objects.get(name=roles.ADMIN))
    StaffProfile.objects.create(user=user, dormitory=dormitory)
    return user


@pytest.fixture
def boss_client(client, boss):
    client.force_login(boss)
    client.cookies["django_language"] = "en"
    return client


@pytest.fixture
def booking(resident, machine, slot, dormitory):
    LedgerEntry.objects.create(resident=resident, kind="credit", amount=100)
    day = local_today(dormitory) + timedelta(days=1)
    return services.book_slots(resident, machine, day, [slot])[0]


def run_action(client, action, booking, **extra):
    data = {"action": action, "_selected_action": [booking.pk], **extra}
    return client.post(CHANGELIST, data)


# --- Bookings are read-only -------------------------------------------------------


def test_bookings_cannot_be_added_changed_or_deleted(boss_client, booking):
    assert boss_client.get(reverse("admin:bookings_booking_add")).status_code == 403
    change_url = reverse("admin:bookings_booking_change", args=[booking.pk])
    page = boss_client.get(change_url)
    assert page.status_code == 200 and not page.context["has_change_permission"]
    boss_client.post(change_url, {"status": "cancelled", "price_rub": 0})
    booking.refresh_from_db()
    assert booking.status == Booking.Status.ACTIVE
    delete_url = reverse("admin:bookings_booking_delete", args=[booking.pk])
    assert boss_client.post(delete_url, {"post": "yes"}).status_code == 403
    assert Booking.objects.filter(pk=booking.pk).exists()
    assert (
        "delete_selected"
        not in boss_client.get(CHANGELIST)
        .context["action_form"]
        .fields["action"]
        .choices.__repr__()
    )


def test_cancel_action_asks_for_a_reason_first(boss_client, booking):
    page = run_action(boss_client, "cancel_with_refund_rule", booking)
    assert page.status_code == 200
    assert page.context["rows"] == [(booking, 50)]
    page = run_action(boss_client, "cancel_with_refund_rule", booking, confirm="yes", reason=" ")
    assert page.context["reason_missing"]
    booking.refresh_from_db()
    assert booking.status == Booking.Status.ACTIVE
    assert not AuditEvent.objects.exists()


def test_cancel_with_refund_rule(boss_client, boss, booking, resident):
    response = run_action(
        boss_client, "cancel_with_refund_rule", booking, confirm="yes", reason="Broken door"
    )
    assert response.status_code == 302
    booking.refresh_from_db()
    assert booking.status == Booking.Status.CANCELLED_BY_ADMIN
    assert booking.cancel_reason == "Broken door"
    assert LedgerEntry.objects.balance(resident) == 100
    event = AuditEvent.objects.get()
    assert (event.action, event.actor) == ("booking.cancel_by_staff", boss)


def test_full_refund_versus_rule_inside_the_cutoff(boss_client, booking, resident, dormitory):
    dormitory.cancellation_cutoff_hours = 72  # tomorrow is inside the cutoff
    dormitory.save()
    preview = run_action(boss_client, "cancel_with_refund_rule", booking)
    assert preview.context["rows"] == [(booking, 0)]
    preview = run_action(boss_client, "cancel_with_full_refund", booking)
    assert preview.context["rows"] == [(booking, 50)]
    run_action(boss_client, "cancel_with_full_refund", booking, confirm="yes", reason="Our fault")
    assert LedgerEntry.objects.balance(resident) == 100
    assert AuditEvent.objects.get().after["full_refund"] is True


def test_bookings_that_cannot_be_cancelled_are_reported(boss_client, booking):
    services.cancel_booking(booking, actor=booking.resident.user)
    response = run_action(
        boss_client, "cancel_with_refund_rule", booking, confirm="yes", reason="x"
    )
    assert response.status_code == 302
    assert not AuditEvent.objects.exists()


# --- Other admin edits are audited ------------------------------------------------


def test_resident_edit_is_audited_with_before_and_after(boss_client, boss, resident):
    url = reverse("admin:accounts_resident_change", args=[resident.pk])
    data = {
        "user": resident.user.pk,
        "dormitory": resident.dormitory.pk,
        "student_code": resident.student_code,
        "full_name": resident.full_name,
        "room": "305",
        "language": "ru",
    }
    assert boss_client.post(url, data).status_code == 302
    event = AuditEvent.objects.get()
    assert (event.action, event.actor) == ("admin.change", boss)
    assert ("room", "101", "305") in event.changes


def test_password_change_is_audited_without_the_password(boss_client, resident):
    url = reverse("admin:auth_user_password_change", args=[resident.user.pk])
    data = {"password1": "N3w-secret-pass!", "password2": "N3w-secret-pass!"}
    assert boss_client.post(url, data).status_code == 302
    event = AuditEvent.objects.get(action="user.password_change")
    assert event.before is None and event.after is None
    assert "N3w-secret" not in str(AuditEvent.objects.values())


def test_manual_ledger_entry_needs_a_note_and_is_audited(boss_client, boss, resident):
    url = reverse("admin:ledger_ledgerentry_add")
    data = {"resident": resident.pk, "kind": "credit", "amount": 200, "note": ""}
    page = boss_client.post(url, data)
    assert page.status_code == 200 and page.context["adminform"].form.errors["note"]
    assert not LedgerEntry.objects.exists()

    data["note"] = "Cash at the desk"
    assert boss_client.post(url, data).status_code == 302
    entry = LedgerEntry.objects.get()
    assert entry.created_by == boss
    event = AuditEvent.objects.get()
    assert (event.action, event.reason) == ("ledger.payment", "Cash at the desk")


def test_machine_added_inline_is_audited(boss_client, dormitory):
    url = reverse("admin:dorms_dormitory_change", args=[dormitory.pk])
    data = {
        "name": dormitory.name,
        "slug": dormitory.slug,
        "timezone": dormitory.timezone,
        "price_per_slot": 50,
        "cancellation_cutoff_hours": 2,
        "booking_horizon_days": 7,
        "time_slots-TOTAL_FORMS": 0,
        "time_slots-INITIAL_FORMS": 0,
        "machines-TOTAL_FORMS": 1,
        "machines-INITIAL_FORMS": 0,
        "machines-0-number": 7,
        "machines-0-active": "on",
    }
    assert boss_client.post(url, data).status_code == 302
    actions = sorted(AuditEvent.objects.values_list("action", "target_type"))
    assert ("admin.add", "dorms.Machine") in actions
    assert ("admin.change", "dorms.Dormitory") in actions


def test_activation_link_actions_are_audited(boss_client, resident):
    url = reverse("admin:accounts_resident_changelist")
    boss_client.post(url, {"action": "reset_pins", "_selected_action": [resident.pk]})
    boss_client.post(url, {"action": "create_activation_links", "_selected_action": [resident.pk]})
    assert sorted(AuditEvent.objects.values_list("action", flat=True)) == [
        "resident.activation_link",
        "resident.pin_reset",
    ]
    # The link itself (a credential) is never stored in the audit log.
    assert "/account/activate/" not in str(AuditEvent.objects.values())


def test_audit_log_is_read_only_in_admin(boss_client, boss):
    from apps.audit.services import record

    event = record(actor=boss, action="admin.add")
    assert boss_client.get(reverse("admin:audit_auditevent_add")).status_code == 403
    delete_url = reverse("admin:audit_auditevent_delete", args=[event.pk])
    assert boss_client.post(delete_url, {"post": "yes"}).status_code == 403


def test_role_changes_are_in_the_audit_event(boss_client, resident):
    """A user's groups (roles) are saved after the user; the event must see them."""
    manager_group = Group.objects.get(name=roles.MANAGER)
    url = reverse("admin:accounts_user_change", args=[resident.user.pk])
    page = boss_client.get(url)
    data = {
        key: value
        for key, value in page.context["adminform"].form.initial.items()
        if value is not None and key not in ("groups", "user_permissions", "password")
    }
    data.update(
        groups=[manager_group.pk],
        is_active="on",
        date_joined_0="2026-01-01",
        date_joined_1="00:00:00",
    )
    response = boss_client.post(url, data)
    assert response.status_code == 302, response.context["adminform"].form.errors
    event = AuditEvent.objects.get(action="admin.change", target_type="accounts.User")
    assert event.after["groups"] == [str(manager_group)]
    assert event.before["groups"] == [roles.RESIDENT]


def test_group_admin_is_audited(boss_client):
    url = reverse("admin:auth_group_add")
    assert boss_client.post(url, {"name": "night-shift"}).status_code == 302
    assert AuditEvent.objects.filter(action="admin.add", target_type="auth.Group").exists()
