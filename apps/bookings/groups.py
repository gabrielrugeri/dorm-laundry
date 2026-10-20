"""Bookings made together (same `group_id`) are shown to residents as one item."""

from dataclasses import dataclass
from itertools import groupby

from django.http import Http404

from .models import Booking


@dataclass
class BookingGroup:
    group_id: object
    bookings: list  # time order

    @property
    def shown(self):
        """The slots to describe: the non-cancelled ones, or all if every slot
        was cancelled."""
        kept = [b for b in self.bookings if not b.is_cancelled]
        return kept or self.bookings

    @property
    def machine(self):
        return self.bookings[0].machine

    @property
    def day(self):
        return self.bookings[0].date

    @property
    def starts_at(self):
        return self.shown[0].starts_at

    @property
    def ends_at(self):
        return self.shown[-1].ends_at

    @property
    def is_cancelled(self):
        return all(b.is_cancelled for b in self.bookings)

    @property
    def admin_reason(self):
        """Why the administration cancelled (some of) these slots, if it did."""
        for booking in self.bookings:
            if booking.status == Booking.Status.CANCELLED_BY_ADMIN:
                return booking.cancel_reason
        return ""

    def active_bookings(self):
        return [b for b in self.bookings if b.status == Booking.Status.ACTIVE]


def group_bookings(bookings):
    """Turn a Booking queryset into BookingGroups, ordered by start time."""
    bookings = bookings.select_related("machine", "slot").order_by("group_id", "starts_at")
    groups = [
        BookingGroup(key, list(items)) for key, items in groupby(bookings, lambda b: b.group_id)
    ]
    return sorted(groups, key=lambda group: group.bookings[0].starts_at)


def resident_groups(resident, bookings=None):
    """The resident's bookings as groups, ordered by start time."""
    if bookings is None:
        bookings = Booking.objects.filter(resident=resident)
    return group_bookings(bookings)


def get_group_or_404(resident, group_id):
    """A group of the resident's own bookings. Anyone else's gives 404, so
    residents cannot learn about other residents' bookings."""
    groups = resident_groups(resident, Booking.objects.filter(resident=resident, group_id=group_id))
    if not groups:
        raise Http404
    return groups[0]
