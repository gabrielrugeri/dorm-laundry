"""Shared pytest fixtures. Every name and code here is fake."""

from datetime import date, time

import pytest
from django.contrib.auth.models import Group

from apps.dorms.models import Dormitory, Machine, TimeSlot


@pytest.fixture(autouse=True)
def private_media(settings, tmp_path):
    """Uploaded receipts and QR codes go to a temporary folder in tests."""
    settings.PRIVATE_MEDIA_ROOT = tmp_path / "private_media"
    return settings.PRIVATE_MEDIA_ROOT


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
    from apps.accounts import pins, roles
    from apps.accounts.models import Resident, User

    user = User(username=f"{dormitory.slug}-{code}")
    pins.set_pin(user, "123456")  # with the pepper, like every real PIN
    user.save()
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


def out_of_service(machine, kind="maintenance", starts_at=None, ends_at=None, reason="Repairs"):
    """Put `machine` under maintenance (or archive it), from long ago unless
    told otherwise. Tests only: the real path is apps/dorms/maintenance.py."""
    from datetime import UTC, datetime

    from apps.dorms.models import MachineUnavailability

    return MachineUnavailability.objects.create(
        machine=machine,
        kind=kind,
        starts_at=starts_at or datetime(2020, 1, 1, tzinfo=UTC),
        ends_at=ends_at,
        reason=reason,
    )
