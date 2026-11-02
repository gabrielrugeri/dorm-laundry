"""Whether a machine can be used: worked out from its maintenance and archive
periods (MachineUnavailability). The one place that answers "is this machine
available for this slot?", for the booking grid, the machine choice, the
booking service and the dashboard.

Periods are half-open, [starts_at, ends_at): a slot [start, end) is affected
when it overlaps a period at all.
"""

from collections import defaultdict

from django.utils import timezone

from .models import MachineUnavailability


def periods(machines):
    """{machine id: [periods]} for these machines."""
    found = defaultdict(list)
    for period in MachineUnavailability.objects.filter(machine__in=machines).order_by("starts_at"):
        found[period.machine_id].append(period)
    return found


def archived_ids(machines, now=None):
    """Ids of machines whose archive period has started: gone for good."""
    now = now or timezone.now()
    return set(
        MachineUnavailability.objects.filter(
            machine__in=machines,
            kind=MachineUnavailability.Kind.ARCHIVE,
            starts_at__lte=now,
        ).values_list("machine_id", flat=True)
    )


def in_use(machines, now=None):
    """The machines that are not archived (they may still be under maintenance)."""
    gone = archived_ids(machines, now)
    return [machine for machine in machines if machine.pk not in gone]


def blocking_period(machine_periods, starts_at, ends_at):
    """The first period that overlaps [starts_at, ends_at), or None."""
    for period in machine_periods:
        if period.overlaps(starts_at, ends_at):
            return period
    return None


def unavailable_slots(machines, day, slots):
    """{(machine id, slot id): period} for the slots of `day` that overlap a
    maintenance or archive period."""
    by_machine = periods(machines)
    blocked = {}
    for machine in machines:
        machine_periods = by_machine.get(machine.pk, [])
        if not machine_periods:
            continue
        for slot in slots:
            starts_at, ends_at = slot.bounds(day)
            period = blocking_period(machine_periods, starts_at, ends_at)
            if period is not None:
                blocked[(machine.pk, slot.pk)] = period
    return blocked


def is_available(machine, day, slots):
    """Whether no maintenance or archive period touches these slots."""
    return not unavailable_slots([machine], day, slots)


def current(machine_periods, now=None):
    """The period in force now, or None (the machine is in service)."""
    now = now or timezone.now()
    for period in machine_periods:
        if period.starts_at <= now and (period.ends_at is None or now < period.ends_at):
            return period
    return None


def upcoming(machine_periods, now=None):
    """Periods that have not started yet, soonest first."""
    now = now or timezone.now()
    return [period for period in machine_periods if period.starts_at > now]
