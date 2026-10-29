import pytest
from django.contrib.auth.models import Group
from django.urls import reverse

from apps.accounts import roles
from apps.accounts.models import StaffProfile, User

HOME = reverse("core:home")
STAFF_HOME = reverse("core:staff_home")


@pytest.fixture
def manager(dormitory):
    user = User.objects.create_user(username="manager")
    user.groups.add(Group.objects.get(name=roles.MANAGER))
    StaffProfile.objects.create(user=user, dormitory=dormitory)
    return user


@pytest.mark.parametrize("url", [HOME, STAFF_HOME])
def test_anonymous_users_are_sent_to_login(client, url):
    response = client.get(url)
    assert response.status_code == 302
    assert response.url.startswith(reverse("accounts:login"))


def test_resident_sees_home(client, resident):
    client.force_login(resident.user)
    assert client.get(HOME).status_code == 200


def test_resident_cannot_open_staff_page(client, resident):
    client.force_login(resident.user)
    assert client.get(STAFF_HOME).status_code == 403


def test_staff_home_redirects_staff(client, manager, settings):
    settings.KEYS_ENABLED = True
    client.force_login(manager)
    response = client.get(HOME)
    assert response.status_code == 302
    assert response.url == STAFF_HOME
    assert client.get(STAFF_HOME).status_code == 200


def test_user_without_role_is_forbidden(client, db):
    client.force_login(User.objects.create_user(username="nobody"))
    assert client.get(HOME).status_code == 403


def test_staff_without_dormitory_is_forbidden(client, db):
    user = User.objects.create_user(username="floating-manager")
    user.groups.add(Group.objects.get(name=roles.MANAGER))
    client.force_login(user)
    assert client.get(STAFF_HOME).status_code == 403


def test_deactivated_resident_loses_access(client, resident):
    client.force_login(resident.user)
    resident.user.is_active = False
    resident.user.save()
    response = client.get(HOME)
    assert response.status_code == 302  # session no longer authenticates


def _routes(patterns, prefix=""):
    for pattern in patterns:
        route = prefix + str(pattern.pattern)
        if hasattr(pattern, "url_patterns"):
            yield from _routes(pattern.url_patterns, route)
        else:
            yield route


def test_no_url_looks_up_residents_by_student_code():
    """Privacy rule: no endpoint (outside the staff-only admin) takes a code."""
    from django.urls import get_resolver

    routes = [r for r in _routes(get_resolver().url_patterns) if not r.startswith("admin/")]
    assert routes  # the walk found something
    assert not [r for r in routes if "code" in r.lower()]
