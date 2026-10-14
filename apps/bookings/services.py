"""Booking service: the only place that creates or cancels bookings.

Views and the admin call these functions instead of touching `Booking` and
`LedgerEntry` directly, so that every booking is charged, every valid
cancellation is refunded, and every check is scoped to one dormitory.

Every function raises a `BookingError` subclass when the action is not
allowed. Its `message` is translatable and safe to show to the resident.
"""

import uuid

from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.accounts.models import Resident
from apps.ledger.models import LedgerEntry

from .models import Booking


class BookingError(Exception):
    """Base class for booking problems the user can be told about."""

    message = _("This booking is not possible.")

    def __init__(self, message=None):
        if message is not None:
            self.message = message
        super().__init__(self.message)


class SlotUnavailable(BookingError):
    message = _("This time slot is no longer available. Please choose another one.")


class InsufficientBalance(BookingError):
    message = _("Your balance is too low for this booking.")


class SlotsNotConsecutive(BookingError):
    message = _("Selected time slots must follow each other without gaps.")


class OutsideBookingWindow(BookingError):
    message = _("This time slot cannot be booked: it is in the past or too far ahead.")


class MachineUnavailable(BookingError):
    message = _("This machine is not available for booking.")


class WrongDormitory(BookingError):
    message = _("This machine or time slot does not belong to your dormitory.")


class AlreadyCancelled(BookingError):
    message = _("This booking has already been cancelled.")


class TooLateToCancel(BookingError):
    message = _("This booking has already started and can no longer be cancelled.")


class NotAllowed(BookingError):
    message = _("You are not allowed to change this booking.")


# --- Checks used by book_slots -------------------------------------------------


def _check_same_dormitory(dormitory, machine, slots):
    if machine.dormitory_id != dormitory.pk:
        raise WrongDormitory
    if any(slot.dormitory_id != dormitory.pk for slot in slots):
        raise WrongDormitory


def _check_bookable(machine, slots):
    if not machine.active:
        raise MachineUnavailable
    if any(not slot.active for slot in slots):
        raise SlotUnavailable


def _check_consecutive(dormitory, slots):
    """`slots` (sorted by start time) must be neighbours among the active slots,
    each one ending exactly when the next one starts."""
    active_ids = list(
        dormitory.time_slots.filter(active=True).order_by("start_time").values_list("pk", flat=True)
    )
    positions = [active_ids.index(slot.pk) for slot in slots]
    if positions != list(range(positions[0], positions[0] + len(slots))):
        raise SlotsNotConsecutive
    for earlier, later in zip(slots, slots[1:], strict=False):
        if earlier.end_time != later.start_time:
            raise SlotsNotConsecutive


def _check_booking_window(dormitory, day, first_slot, now):
    """The first slot must start in the future, and `day` must be within the
    dormitory's booking horizon (today counts as the first day)."""
    today = now.astimezone(dormitory.tzinfo).date()
    if (day - today).days >= dormitory.booking_horizon_days:
        raise OutsideBookingWindow
    starts_at, _ends_at = first_slot.bounds(day)
    if starts_at <= now:
        raise OutsideBookingWindow


# --- Booking --------------------------------------------------------------------


def book_slots(resident, machine, day, slots, *, now=None):
    """Book `machine` for one or more consecutive `slots` on local date `day`.

    Creates one Booking per slot, all sharing a new `group_id`, and charges
    the dormitory's price for each slot as a separate ledger entry. Either
    every slot is booked and charged, or nothing is.

    Returns the new bookings in time order. Raises a BookingError if the
    booking is not possible.
    """
    if not slots:
        raise ValueError("book_slots() needs at least one slot.")
    now = now or timezone.now()
    dormitory = resident.dormitory
    slots = sorted(slots, key=lambda slot: slot.start_time)

    _check_same_dormitory(dormitory, machine, slots)
    _check_bookable(machine, slots)
    _check_consecutive(dormitory, slots)
    _check_booking_window(dormitory, day, slots[0], now)

    price = dormitory.price_per_slot
    try:
        with transaction.atomic():
            # Lock the resident's row, so two requests from the same resident run one
            # after the other and cannot both spend the same balance. (SQLite already
            # serialises all writes; on PostgreSQL this lock is what does it.)
            Resident.objects.select_for_update().get(pk=resident.pk)
            if LedgerEntry.objects.balance(resident) < price * len(slots):
                raise InsufficientBalance

            group_id = uuid.uuid4()
            bookings = []
            for slot in slots:
                booking = Booking.objects.create(
                    machine=machine,
                    date=day,
                    slot=slot,
                    resident=resident,
                    group_id=group_id,
                    price_rub=price,
                )
                if price:
                    LedgerEntry.objects.create(
                        resident=resident,
                        amount=-price,
                        kind=LedgerEntry.Kind.BOOKING,
                        booking=booking,
                    )
                bookings.append(booking)
    except IntegrityError:
        # The database refused a booking: normally because someone else took one of
        # these slots a moment ago. Anything else is a bug, so let it through.
        if _any_slot_occupied(machine, day, slots):
            raise SlotUnavailable from None
        raise
    return bookings


def _any_slot_occupied(machine, day, slots):
    return (
        Booking.objects.filter(machine=machine, date=day, slot__in=slots)
        .exclude(status=Booking.Status.CANCELLED)
        .exists()
    )
