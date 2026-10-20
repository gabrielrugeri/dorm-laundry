"""What the manager's key screen shows: the day's bookings with their key
status, and every key that is out right now.

Staff-only: these rows include residents' names and rooms.
"""

from dataclasses import dataclass

from django.utils import timezone

from apps.bookings.groups import BookingGroup, group_bookings
from apps.bookings.models import Booking

from . import services
from .models import KeyLog


@dataclass
class ScheduleRow:
    group: BookingGroup
    log: KeyLog | None
    now: object

    @property
    def resident(self):
        return self.group.bookings[0].resident

    @property
    def status(self):
        if self.log and self.log.returned_at:
            return "returned"
        if self.log and self.log.taken_at:
            return "taken"
        return "waiting"

    @property
    def overdue(self):
        return self.status == "taken" and self.now > self.group.ends_at

    @property
    def can_undo(self):
        return services.can_undo(self.log, self.now)


def day_rows(dormitory, day, now=None):
    """One row per booking group on `day` (cancelled slots left out), by time."""
    now = now or timezone.now()
    bookings = (
        Booking.objects.filter(machine__dormitory=dormitory, date=day)
        .exclude(status__in=Booking.CANCELLED_STATUSES)
        .select_related("resident")
    )
    groups = group_bookings(bookings)
    logs = {
        log.booking.group_id: log
        for log in KeyLog.objects.filter(
            booking__group_id__in=[g.group_id for g in groups]
        ).select_related("booking")
    }
    return [ScheduleRow(group, logs.get(group.group_id), now) for group in groups]


@dataclass
class KeyOut:
    log: KeyLog
    due_at: object
    overdue: bool

    @property
    def booking(self):
        return self.log.booking


def keys_out(dormitory, now=None):
    """Keys taken and not returned, from any day; overdue ones first."""
    now = now or timezone.now()
    logs = KeyLog.objects.filter(
        booking__machine__dormitory=dormitory,
        taken_at__isnull=False,
        returned_at__isnull=True,
    ).select_related("booking__resident", "booking__machine")
    out = []
    for log in logs:
        due_at = log.due_at
        out.append(KeyOut(log, due_at, now > due_at))
    return sorted(out, key=lambda key: (not key.overdue, key.log.taken_at))
