"""Read-only questions the booking screens ask: which days can be booked,
where a machine is free for N slots in a row, and why a machine is not.

Privacy: these functions return counts, machines and the asking resident's
own bookings only, never other residents' bookings.
"""

from dataclasses import dataclass
from datetime import timedelta

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
        status__in=Booking.CANCELLED_STATUSES
    )


def following_slots(dormitory, first_slot, slots=None):
    """`first_slot` and the active slots right after it, without gaps: the
    slots that could be booked together starting at `first_slot`."""
    slots = slots if slots is not None else active_slots(dormitory)
    run = slots[slots.index(first_slot) :]
    for n, (earlier, later) in enumerate(zip(run, run[1:], strict=False), start=1):
        if earlier.end_time != later.start_time:
            return run[:n]
    return run


def max_length(dormitory):
    """The longest run of back-to-back active slots in a day: the most slots
    one booking can take."""
    slots = active_slots(dormitory)
    return max((len(following_slots(dormitory, s, slots)) for s in slots), default=0)


def slot_hours(dormitory):
    """Hours per slot if every active slot has the same length, else None."""
    durations = {s.duration_minutes for s in active_slots(dormitory)}
    if len(durations) == 1:
        minutes = durations.pop()
        return minutes // 60 if minutes % 60 == 0 else minutes / 60
    return None


@dataclass
class StartOption:
    """A start time where at least one machine is free for `length` slots."""

    slot: object
    slots: list  # the `length` slots booked together
    free: int

    @property
    def end_time(self):
        return self.slots[-1].end_time


def start_options(dormitory, day, length, now=None):
    """Start times on `day` where at least one active machine is free for
    `length` consecutive slots, and how many machines are. Started slots and
    runs that would not fit before the day ends are left out."""
    now = now or timezone.now()
    machines = list(dormitory.machines.filter(active=True))
    taken = set(occupied(machines, day).values_list("machine_id", "slot_id"))
    slots = active_slots(dormitory)
    options = []
    for slot in slots:
        run = following_slots(dormitory, slot, slots)[:length]
        if len(run) < length or slot.bounds(day)[0] <= now:
            continue
        free = sum(all((m.pk, s.pk) not in taken for s in run) for m in machines)
        if free:
            options.append(StartOption(slot, run, free))
    return options


# Why a machine cannot be booked for the chosen slots.
FREE = "free"
BOOKED = "booked"
FREE_UNTIL = "free_until"
OUT_OF_SERVICE = "out_of_service"


@dataclass
class MachineChoice:
    machine: object
    state: str
    free_until: object = None  # end time of the last free slot, for FREE_UNTIL

    @property
    def available(self):
        return self.state == FREE


def machine_choices(dormitory, day, run):
    """Every machine of the dormitory (active or not), and whether it is free
    for all slots in `run`. Machines free at the start but not for the whole
    run say until when they are free."""
    machines = list(dormitory.machines.order_by("number"))
    taken = set(occupied(machines, day).filter(slot__in=run).values_list("machine_id", "slot_id"))
    choices = []
    for machine in machines:
        if not machine.active:
            choices.append(MachineChoice(machine, OUT_OF_SERVICE))
            continue
        free_count = 0
        for slot in run:
            if (machine.pk, slot.pk) in taken:
                break
            free_count += 1
        if free_count == len(run):
            choices.append(MachineChoice(machine, FREE))
        elif free_count == 0:
            choices.append(MachineChoice(machine, BOOKED))
        else:
            choices.append(MachineChoice(machine, FREE_UNTIL, run[free_count - 1].end_time))
    return choices
