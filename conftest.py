"""Shared pytest fixtures. Every name and code here is fake."""

from datetime import time

import pytest

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
    return Machine.objects.create(dormitory=dormitory, label="Machine 1")
