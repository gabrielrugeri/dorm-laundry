"""Django admin is for superusers only (docs/CLAUDE.md hard rule 10)."""

import pytest
from django.urls import reverse

from apps.accounts import roles
from apps.keylog.tests.test_services import make_staff

ADMIN = reverse("admin:index")


@pytest.mark.parametrize("role", [roles.ADMIN, roles.MANAGER])
def test_dormitory_staff_cannot_open_django_admin(client, dormitory, role):
    user = make_staff(dormitory, "staff", role=role)
    user.is_staff = True  # even with Django's staff flag
    user.save()
    client.force_login(user)
    response = client.get(ADMIN)
    assert response.status_code == 302
    assert reverse("admin:login") in response.url
    assert client.get(reverse("admin:bookings_booking_changelist")).status_code == 302


def test_residents_cannot_open_django_admin(client, resident):
    client.force_login(resident.user)
    assert client.get(ADMIN).status_code == 302


def test_superusers_can(client, admin_user):
    client.force_login(admin_user)
    assert client.get(ADMIN).status_code == 200


def test_seed_demo_admin_is_not_a_superuser(db):
    from django.core.management import call_command

    from apps.accounts.models import User

    call_command("seed_demo")
    admin = User.objects.get(username="admin")
    assert not admin.is_superuser and not admin.is_staff
    assert roles.has_role(admin, roles.ADMIN)
