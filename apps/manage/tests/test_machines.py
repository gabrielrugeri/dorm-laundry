"""The machines screens: form -> preview -> confirm, end, archive, and the
residents' notice. Every name here is fake."""

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.accounts import roles
from apps.bookings import services as booking_services
from apps.bookings.availability import local_today
from apps.bookings.models import Booking
from apps.dorms.models import MachineUnavailability
from apps.keylog.tests.test_services import make_staff
from apps.ledger.models import LedgerEntry

LIST = reverse("manage:machines")


@pytest.fixture
def boss_client(client, dormitory):
    client.force_login(make_staff(dormitory, "boss", role=roles.ADMIN))
    client.cookies["django_language"] = "en"
    return client


def url(name, pk):
    return reverse(f"manage:{name}", kwargs={"pk": pk})


@pytest.fixture
def booked(resident, machine, slot, dormitory):
    LedgerEntry.objects.create(resident=resident, kind="credit", amount=50)
    day = local_today(dormitory) + timedelta(days=2)
    [booking] = booking_services.book_slots(resident, machine, day, [slot])
    return booking


def test_admins_only(client, dormitory, resident, machine):
    manager = make_staff(dormitory, "keys", role=roles.MANAGER)
    for target in (
        LIST,
        url("machine_maintenance", machine.pk),
        url("machine_archive", machine.pk),
    ):
        client.force_login(resident.user)
        assert client.get(target).status_code == 403
        client.force_login(manager)
        assert client.get(target).status_code == 403


def test_list_shows_machines_and_actions(boss_client, machine):
    html = boss_client.get(LIST).content.decode()
    assert machine.name in html and "In service" in html
    assert url("machine_maintenance", machine.pk) in html


def test_maintenance_preview_then_confirm(boss_client, machine, booked, resident):
    target = url("machine_maintenance", machine.pk)
    data = {"starts": "now", "ends": "open", "reason": "Water leak", "refund": "on"}
    preview = boss_client.post(target, data)
    html = preview.content.decode()
    assert "1 booking will be cancelled" in html and resident.full_name in html
    assert not MachineUnavailability.objects.exists()  # nothing happened yet
    booked.refresh_from_db()
    assert booked.status == Booking.Status.ACTIVE

    done = boss_client.post(target, {**data, "confirm": "1"})
    assert done.status_code == 302 and done.url == LIST
    booked.refresh_from_db()
    assert booked.status == Booking.Status.CANCELLED_BY_ADMIN
    assert "Water leak" in booked.cancel_reason
    assert LedgerEntry.objects.balance(resident) == 50  # refunded


def test_unticked_refund_box_is_kept(boss_client, machine, booked):
    target = url("machine_maintenance", machine.pk)
    data = {"starts": "now", "ends": "open", "reason": "Leak", "confirm": "1"}  # no "refund"
    boss_client.post(target, data)
    assert MachineUnavailability.objects.get().refund is False


def test_later_start_needs_a_time_and_past_is_refused(boss_client, machine):
    target = url("machine_maintenance", machine.pk)
    page = boss_client.post(target, {"starts": "later", "ends": "open", "reason": "x"})
    assert page.context["form"].errors["starts_at"]
    past = (timezone.localtime() - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")
    page = boss_client.post(
        target,
        {"starts": "later", "starts_at": past, "ends": "open", "reason": "x", "confirm": "1"},
    )
    assert "cannot be in the past" in page.content.decode()
    assert not MachineUnavailability.objects.exists()


def test_end_maintenance(boss_client, machine):
    from conftest import out_of_service

    period = out_of_service(machine)
    page = boss_client.get(url("period_end", period.pk))
    assert "can be booked again" in page.content.decode()
    boss_client.post(url("period_end", period.pk))
    period.refresh_from_db()
    assert period.ends_at is not None and period.ends_at <= timezone.now()


def test_archive_needs_the_forever_tick(boss_client, machine):
    target = url("machine_archive", machine.pk)
    page = boss_client.post(target, {"reason": "Replaced", "refund": "on"})
    assert page.context["form"].errors["confirm_forever"]
    data = {"reason": "Replaced", "refund": "on", "confirm_forever": "on", "confirm": "1"}
    boss_client.post(target, data)
    period = MachineUnavailability.objects.get()
    assert period.kind == "archive" and period.ends_at is None
    html = boss_client.get(LIST).content.decode()
    assert "1 machine taken out of use" in html


def test_other_dormitory_machines_are_hidden(boss_client, other_dormitory):
    from apps.dorms.models import Machine

    foreign = Machine.objects.create(dormitory=other_dormitory, number=9)
    assert boss_client.get(url("machine_maintenance", foreign.pk)).status_code == 404


def test_admin_navigation_has_machines_and_history_moved_to_settings(boss_client):
    html = boss_client.get(reverse("manage:residents")).content.decode()
    assert f'href="{LIST}"' in html
    assert reverse("manage:audit") in boss_client.get(reverse("manage:settings")).content.decode()


# --- Residents ---------------------------------------------------------------------------


def test_residents_see_a_maintenance_notice(client, resident, machine):
    from conftest import out_of_service

    out_of_service(machine, ends_at=timezone.now() + timedelta(days=1))
    client.force_login(resident.user)
    client.cookies["django_language"] = "en"
    html = client.get(reverse("core:home")).content.decode()
    assert "Machine 1:" in html and "under maintenance" in html


def test_archived_machines_give_no_notice(client, resident, machine):
    from conftest import out_of_service

    out_of_service(machine, kind="archive")
    client.force_login(resident.user)
    client.cookies["django_language"] = "en"
    assert "under maintenance" not in client.get(reverse("core:home")).content.decode()
