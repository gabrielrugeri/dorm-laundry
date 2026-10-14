"""Booking service: the only place that creates or cancels bookings.

Views and the admin call these functions instead of touching `Booking` and
`LedgerEntry` directly, so that every booking is charged, every valid
cancellation is refunded, and every check is scoped to one dormitory.

Every function raises a `BookingError` subclass when the action is not
allowed. Its `message` is translatable and safe to show to the resident.
"""

from django.utils.translation import gettext_lazy as _


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
