"""Read-only questions the booking screens ask: which days can be booked, how
many machines are free per slot, and how long a machine stays free.

Privacy: these functions return counts, machines and the asking resident's
own bookings only, never other residents' bookings.
"""

from dataclasses import dataclass
from datetime import timedelta

from django.db.models import Count
from django.utils import timezone

from .models import Booking


def local_today(dormitory, now=None):
    return (now or timezone.now()).astimezone(dormitory.tzinfo).date()


def booking_days(dormitory, now=None):
    """Today and the following days residents may book (the booking horizon)."""
    today = local_today(dormitory, now)
    return [today + timedelta(days=n) for n in range(dormitory.booking_horizon_days)]


def active_slots(dormitory):
    return list(dormitory.time_slots.filter(active=True).order_by("start_time"))


def occupied(machine_queryset, day):
    """Non-cancelled bookings for these machines on `day`."""
    return Booking.objects.filter(machine__in=machine_queryset, date=day).exclude(
        status=Booking.Status.CANCELLED
    )


@dataclass
class SlotAvailability:
    slot: object
    starts_at: object
    free: int
    total: int
    mine: bool
    started: bool
    finished: bool

    @property
    def bookable(self):
        return self.free > 0 and not self.started


def day_availability(dormitory, resident, day, now=None):
    """One SlotAvailability per active slot of `day`, in time order."""
    now = now or timezone.now()
    machines = dormitory.machines.filter(active=True)
    total = machines.count()
    taken = occupied(machines, day)
    counts = dict(taken.values_list("slot").annotate(n=Count("pk")))
    mine = set(taken.filter(resident=resident).values_list("slot", flat=True))
    rows = []
    for slot in active_slots(dormitory):
        starts_at, ends_at = slot.bounds(day)
        rows.append(
            SlotAvailability(
                slot=slot,
                starts_at=starts_at,
                free=total - counts.get(slot.pk, 0),
                total=total,
                mine=slot.pk in mine,
                started=starts_at <= now,
                finished=ends_at <= now,
            )
        )
    return rows


def following_slots(dormitory, first_slot):
    """`first_slot` and the active slots right after it, without gaps: the
    slots that could be booked together starting at `first_slot`."""
    slots = active_slots(dormitory)
    run = slots[slots.index(first_slot) :]
    for n, (earlier, later) in enumerate(zip(run, run[1:], strict=False), start=1):
        if earlier.end_time != later.start_time:
            return run[:n]
    return run


def free_runs(dormitory, day, first_slot):
    """For each active machine free at `first_slot`: how many consecutive slots
    (starting at `first_slot`) it stays free.

    Returns ([(machine, count), ...], slots), where `slots` are the slots that
    could follow `first_slot` (see following_slots)."""
    slots = following_slots(dormitory, first_slot)
    machines = list(dormitory.machines.filter(active=True).order_by("label"))
    taken = set(occupied(machines, day).filter(slot__in=slots).values_list("machine_id", "slot_id"))
    runs = []
    for machine in machines:
        count = 0
        for slot in slots:
            if (machine.pk, slot.pk) in taken:
                break
            count += 1
        if count:
            runs.append((machine, count))
    return runs, slots
