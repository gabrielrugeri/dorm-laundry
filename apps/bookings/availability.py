"""Read-only questions the booking screens ask: which days can be booked,
where a machine is free for N slots in a row, and why a machine is not.

Privacy: these functions return counts, machines and the asking resident's
own bookings only, never other residents' bookings.
"""

from dataclasses import dataclass
from datetime import timedelta

from django.utils import timezone

from apps.dorms import machine_state

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
    machines = machine_state.in_use(list(dormitory.machines.all()), now)
    taken = set(occupied(machines, day).values_list("machine_id", "slot_id"))
    slots = active_slots(dormitory)
    # Slots under maintenance count as taken.
    taken |= set(machine_state.unavailable_slots(machines, day, slots))
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
MAINTENANCE = "maintenance"


@dataclass
class MachineChoice:
    machine: object
    state: str
    free_until: object = None  # end time of the last free slot, for FREE_UNTIL
    until: object = None  # end of the maintenance (a datetime, or None if open), for MAINTENANCE

    @property
    def available(self):
        return self.state == FREE


def machine_choices(dormitory, day, run):
    """Every machine in use (archived ones are gone), and whether it is free
    for all slots in `run`. Machines free at the start but not for the whole
    run say until when they are free; machines under maintenance say until
    when."""
    machines = machine_state.in_use(list(dormitory.machines.order_by("number")))
    taken = set(occupied(machines, day).filter(slot__in=run).values_list("machine_id", "slot_id"))
    blocked = machine_state.unavailable_slots(machines, day, run)
    choices = []
    for machine in machines:
        period = blocked.get((machine.pk, run[0].pk))
        if period is not None:
            choices.append(MachineChoice(machine, MAINTENANCE, until=period.ends_at))
            continue
        free_count = 0
        for slot in run:
            if (machine.pk, slot.pk) in taken or (machine.pk, slot.pk) in blocked:
                break
            free_count += 1
        if free_count == len(run):
            choices.append(MachineChoice(machine, FREE))
        elif free_count == 0:
            choices.append(MachineChoice(machine, BOOKED))
        else:
            choices.append(MachineChoice(machine, FREE_UNTIL, run[free_count - 1].end_time))
    return choices


def maintenance_notices(dormitory, now=None):
    """[(machine, period, started)] for maintenance that is on now or starts
    within the booking horizon, so residents see it before they choose."""
    now = now or timezone.now()
    horizon_end = now + timedelta(days=dormitory.booking_horizon_days + 1)
    machines = machine_state.in_use(list(dormitory.machines.order_by("number")), now)
    by_machine = machine_state.periods(machines)
    notices = []
    for machine in machines:
        for period in by_machine.get(machine.pk, []):
            if period.overlaps(now, horizon_end):
                notices.append((machine, period, period.starts_at <= now))
    return notices
