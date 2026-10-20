"""Shared pytest fixtures. Every name and code here is fake."""

from datetime import date, time

import pytest
from django.contrib.auth.models import Group

from apps.dorms.models import Dormitory, Machine, TimeSlot


@pytest.fixture
def dormitory(db):
    return Dormitory.objects.create(name="Test Dormitory", slug="test")


@pytest.fixture
def other_dormitory(db):
    return Dormitory.objects.create(name="Other Dormitory", slug="other")


@pytest.fixture
def slot(dormitory):
    return TimeSlot.objects.create(dormitory=dormitory, start_time=time(8, 0))


@pytest.fixture
def machine(dormitory):
    return Machine.objects.create(dormitory=dormitory, number=1)


def make_resident(dormitory, code, name="Test Resident", room="101"):
    from apps.accounts import roles
    from apps.accounts.models import Resident, User

    user = User.objects.create_user(username=f"{dormitory.slug}-{code}", password="123456")
    user.groups.add(Group.objects.get(name=roles.RESIDENT))
    return Resident.objects.create(
        user=user, dormitory=dormitory, student_code=code, full_name=name, room=room
    )


@pytest.fixture
def resident(dormitory):
    return make_resident(dormitory, "S0001", name="Ivan Testov", room="101")


@pytest.fixture
def other_resident(dormitory):
    return make_resident(dormitory, "S0002", name="Anna Fakeova", room="202")


@pytest.fixture
def make_booking(machine, slot, resident):
    """Factory: make_booking(**overrides) creates an active booking."""
    from apps.bookings.models import Booking

    def _make(**kwargs):
        values = {
            "machine": machine,
            "slot": slot,
            "resident": resident,
            "date": date(2026, 10, 14),
            "price_rub": 50,
        }
        values.update(kwargs)
        return Booking.objects.create(**values)

    return _make


def pytest_collection_modifyitems(config, items):
    """Skip tests marked `postgres` unless the test database is PostgreSQL."""
    from django.conf import settings

    if settings.DATABASES["default"]["ENGINE"] == "django.db.backends.postgresql":
        return
    skip = pytest.mark.skip(reason="needs PostgreSQL (set DATABASE_URL)")
    for item in items:
        if "postgres" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(autouse=True)
def _clear_cache():
    """Login lockout counters live in the cache; start every test clean."""
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()
