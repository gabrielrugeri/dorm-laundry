from datetime import UTC, date, datetime, time

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from apps.dorms.models import Dormitory, Machine, TimeSlot


def test_slot_bounds_are_in_dormitory_timezone(slot):
    start, end = slot.bounds(date(2026, 10, 14))
    # 08:00 Moscow (UTC+3) is 05:00 UTC.
    assert start == datetime(2026, 10, 14, 5, 0, tzinfo=UTC)
    assert end == datetime(2026, 10, 14, 7, 0, tzinfo=UTC)


def test_slot_must_end_same_day(dormitory):
    slot = TimeSlot(dormitory=dormitory, start_time=time(23, 0), duration_minutes=120)
    with pytest.raises(ValidationError):
        slot.full_clean()


def test_slot_label(slot):
    assert str(slot) == "08:00–10:00"


def test_slot_start_unique_per_dormitory(slot, dormitory):
    with pytest.raises(IntegrityError):
        TimeSlot.objects.create(dormitory=dormitory, start_time=time(8, 0))


def test_same_slot_time_allowed_in_other_dormitory(slot, other_dormitory):
    TimeSlot.objects.create(dormitory=other_dormitory, start_time=time(8, 0))


def test_machine_label_unique_per_dormitory(machine, dormitory, other_dormitory):
    Machine.objects.create(dormitory=other_dormitory, number=machine.number)
    with pytest.raises(IntegrityError):
        Machine.objects.create(dormitory=dormitory, number=machine.number)


def test_unknown_timezone_rejected(db):
    dorm = Dormitory(name="X", slug="x", timezone="Mars/Olympus")
    with pytest.raises(ValidationError):
        dorm.full_clean()


def test_machine_name_follows_the_language(machine):
    from django.utils import translation

    with translation.override("ru"):
        assert machine.name == "Машина 1"
    with translation.override("en"):
        assert str(machine) == "Machine 1"


@pytest.mark.django_db(transaction=True)
def test_label_migration_turns_labels_into_numbers():
    """Labels with digits keep their number; others get the next free one."""
    from django.db import connection
    from django.db.migrations.executor import MigrationExecutor

    executor = MigrationExecutor(connection)
    executor.migrate([("dorms", "0001_initial")])
    old_apps = executor.loader.project_state([("dorms", "0001_initial")]).apps
    OldDorm = old_apps.get_model("dorms", "Dormitory")
    OldMachine = old_apps.get_model("dorms", "Machine")
    dorm = OldDorm.objects.create(name="Old", slug="old")
    for label in ["Machine 3", "Big one", "Machine 1"]:
        OldMachine.objects.create(dormitory=dorm, label=label)

    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate(executor.loader.graph.leaf_nodes())
    numbers = dict(Machine.objects.filter(dormitory__slug="old").values_list("pk", "number"))
    assert sorted(numbers.values()) == [1, 2, 3]
