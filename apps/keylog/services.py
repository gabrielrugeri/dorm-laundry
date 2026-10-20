"""Recording key hand-overs: the only code that changes KeyLog rows.

The manager taps "key taken" and "key returned" on the schedule. Times are
always the server's clock. A key belongs to a booking group (slots booked
together); its KeyLog is attached to the group's first booking.

Each function raises a KeyActionError subclass when the action is not allowed;
its `message` is translated and safe to show.
"""

from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.accounts.decorators import get_user_dormitory, is_staff_member
from apps.bookings.models import Booking

from .models import KeyLog

# A tap can be undone for this long, to fix mis-taps on a phone. Older
# corrections are made in the admin.
UNDO_WINDOW = timedelta(minutes=10)


class KeyActionError(Exception):
    message = _("This key action is not possible.")

    def __init__(self, message=None):
        if message is not None:
            self.message = message
        super().__init__(str(self.message))


class NotAllowed(KeyActionError):
    message = _("Only staff of this dormitory can record keys.")


class BookingCancelled(KeyActionError):
    message = _("This booking was cancelled.")


class KeyNotTaken(KeyActionError):
    message = _("The key has not been taken yet.")


class NothingToUndo(KeyActionError):
    message = _("There is nothing to undo, or it is too late to undo it.")


def _locked_log(group_id, actor):
    """The group's KeyLog (created on first use), locked for this transaction."""
    dormitory = get_user_dormitory(actor)
    if not (actor.is_active and is_staff_member(actor) and dormitory):
        raise NotAllowed
    bookings = Booking.objects.filter(group_id=group_id, machine__dormitory=dormitory)
    # Lock the group's bookings so two taps on the same key run one after the other.
    first = bookings.select_for_update().order_by("starts_at").first()
    if first is None:
        raise NotAllowed
    if not bookings.exclude(status__in=Booking.CANCELLED_STATUSES).exists():
        raise BookingCancelled
    log, _created = KeyLog.objects.get_or_create(booking=first)
    return log


def _record(log, actor, note):
    log.recorded_by = actor
    note = note.strip()
    if note:
        log.note = f"{log.note}\n{note}".strip()
    log.save()
    return log


def take_key(group_id, *, actor, note="", now=None):
    """Record that the resident took the key. Tapping twice changes nothing."""
    with transaction.atomic():
        log = _locked_log(group_id, actor)
        if log.taken_at is None:
            log.taken_at = now or timezone.now()
        return _record(log, actor, note)


def return_key(group_id, *, actor, note="", now=None):
    """Record that the key came back. Tapping twice changes nothing."""
    with transaction.atomic():
        log = _locked_log(group_id, actor)
        if log.taken_at is None:
            raise KeyNotTaken
        if log.returned_at is None:
            log.returned_at = max(now or timezone.now(), log.taken_at)
        return _record(log, actor, note)


def undo_last(group_id, *, actor, now=None):
    """Undo the latest tap (return, else take) if it was less than UNDO_WINDOW ago."""
    now = now or timezone.now()
    with transaction.atomic():
        log = _locked_log(group_id, actor)
        if log.returned_at and now - log.returned_at <= UNDO_WINDOW:
            log.returned_at = None
        elif log.taken_at and not log.returned_at and now - log.taken_at <= UNDO_WINDOW:
            log.taken_at = None
        else:
            raise NothingToUndo
        return _record(log, actor, "")


def can_undo(log, now=None):
    if log is None:
        return False
    now = now or timezone.now()
    last = log.returned_at or log.taken_at
    return last is not None and now - last <= UNDO_WINDOW
