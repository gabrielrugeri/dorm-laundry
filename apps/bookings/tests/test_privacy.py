"""Privacy and access rules across every resident page. Every name is fake."""

from datetime import time, timedelta

import pytest
from django.contrib.auth.models import Group
from django.urls import reverse

from apps.accounts import roles
from apps.accounts.models import StaffProfile, User
from apps.bookings import availability, services
from apps.dorms.models import TimeSlot
from apps.ledger.models import LedgerEntry
from conftest import make_resident


@pytest.fixture
def scene(dormitory, machine, slot, resident):
    """The logged-in resident and a neighbour both have bookings tomorrow."""
    neighbour = make_resident(dormitory, "ZQ-4242", name="Zinaida Uniquova", room="Z-777")
    slot_10 = TimeSlot.objects.create(dormitory=dormitory, start_time=time(10, 0))
    tomorrow = availability.local_today(dormitory) + timedelta(days=1)
    for person in (resident, neighbour):
        LedgerEntry.objects.create(resident=person, kind="credit", amount=200)
    own = services.book_slots(resident, machine, tomorrow, [slot])
    services.book_slots(neighbour, machine, tomorrow, [slot_10])
    return {"neighbour": neighbour, "own": own[0], "tomorrow": tomorrow, "slot_10": slot_10}


def resident_urls(scene, slot):
    own, tomorrow = scene["own"], scene["tomorrow"]
    return [
        reverse("core:home") + f"?day={tomorrow.isoformat()}",
        reverse("bookings:book", kwargs={"day": tomorrow, "slot_id": slot.pk}),
        reverse("bookings:book", kwargs={"day": tomorrow, "slot_id": scene["slot_10"].pk}),
        reverse("bookings:mine"),
        reverse("bookings:detail", kwargs={"group_id": own.group_id}),
        reverse("bookings:cancel", kwargs={"group_id": own.group_id}),
        reverse("bookings:calendar", kwargs={"group_id": own.group_id}),
        reverse("ledger:balance"),
    ]


def test_no_resident_page_reveals_other_residents(client, resident, slot, scene):
    client.force_login(resident.user)
    neighbour = scene["neighbour"]
    for url in resident_urls(scene, slot):
        response = client.get(url)
        assert response.status_code == 200, url
        body = response.content.decode()
        for secret in (neighbour.full_name, neighbour.room, neighbour.student_code):
            assert secret not in body, f"{secret!r} leaked on {url}"


def test_anonymous_users_are_sent_to_login(client, slot, scene):
    for url in resident_urls(scene, slot):
        response = client.get(url)
        assert response.status_code == 302, url
        assert response.url.startswith(reverse("accounts:login"))


def test_staff_cannot_open_resident_pages(client, dormitory, slot, scene):
    manager = User.objects.create_user(username="manager")
    manager.groups.add(Group.objects.get(name=roles.MANAGER))
    StaffProfile.objects.create(user=manager, dormitory=dormitory)
    client.force_login(manager)
    for url in resident_urls(scene, slot)[1:]:  # the home page redirects staff instead
        assert client.get(url).status_code == 403, url
