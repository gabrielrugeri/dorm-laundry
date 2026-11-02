"""Taking machines out of service: maintenance and archive (Stage 2).

The one way to change MachineUnavailability records. Every change:
- is shown first as a preview: the future bookings it will cancel, and
  bookings already in progress, listed separately for the admin to decide;
- then runs in one transaction with the machine's row locked: the period is
  saved, affected future bookings are cancelled by the administration (the
  residents see the reason), refunded in full if the admin left the
  "Refund affected residents" box ticked (otherwise the usual cancellation
  rule applies), and the change is recorded in the history.

Rules: the end is after the start; the start is not in the past (choose
"starting now" instead); periods of one machine never overlap (extend or end
the existing one instead); an archive has no end and is never undone.
Ending maintenance makes the machine bookable from that moment.
"""

from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.accounts import roles
from apps.accounts.decorators import get_user_dormitory
from apps.audit.services import record, snapshot
from apps.bookings import services as booking_services
from apps.bookings.models import Booking

from .models import Machine, MachineUnavailability

# A start this close to now counts as "now" (the form took a moment to send).
NOW_TOLERANCE = timedelta(minutes=2)


class MaintenanceError(Exception):
    """`message` is translatable and safe to show to the admin."""

    def __init__(self, message):
        super().__init__(message)
        self.message = message


class NotAllowed(Exception):
    pass


def _check_actor(actor, machine):
    if not (roles.has_role(actor, roles.ADMIN) and get_user_dormitory(actor) == machine.dormitory):
        raise NotAllowed


def affected(machine, starts_at, ends_at, now=None):
    """(future, in_progress): the machine's bookings that overlap
    [starts_at, ends_at) (ends_at None = open-ended). Future ones will be
    cancelled; ones already in progress are left for the admin to decide."""
    now = now or timezone.now()
    bookings = (
        Booking.objects.filter(machine=machine, ends_at__gt=starts_at)
        .exclude(status__in=Booking.CANCELLED_STATUSES)
        .select_related("resident", "slot")
        .order_by("starts_at")
    )
    if ends_at is not None:
        bookings = bookings.filter(starts_at__lt=ends_at)
    future = [b for b in bookings if b.starts_at > now]
    in_progress = [b for b in bookings if b.starts_at <= now < b.ends_at]
    return future, in_progress


def _validate(machine, kind, starts_at, ends_at, now, exclude=None):
    if kind == MachineUnavailability.Kind.ARCHIVE and ends_at is not None:
        raise MaintenanceError(_("An archived machine has no end date."))
    if ends_at is not None and ends_at <= starts_at:
        raise MaintenanceError(_("The end must be after the start."))
    if starts_at < now - NOW_TOLERANCE:
        raise MaintenanceError(_("The start cannot be in the past. Choose “starting now”."))
    others = MachineUnavailability.objects.filter(machine=machine)
    if exclude is not None:
        others = others.exclude(pk=exclude.pk)
    for other in others:
        if other.overlaps(starts_at, ends_at or starts_at + timedelta(days=36500)):
            if other.kind == MachineUnavailability.Kind.ARCHIVE:
                raise MaintenanceError(_("This machine is archived."))
            raise MaintenanceError(
                _(
                    "This overlaps another maintenance period of this machine. "
                    "Extend or end that one instead."
                )
            )


def _cancel(bookings, actor, label, reason, refund, now):
    for booking in bookings:
        booking_services.cancel_booking(
            booking, actor=actor, reason=f"{label}: {reason}", full_refund=refund, now=now
        )
    return len(bookings)


def _label(kind):
    if kind == MachineUnavailability.Kind.ARCHIVE:
        return str(_("The machine was taken out of use"))
    return str(_("The machine is under maintenance"))


def take_out_of_service(*, actor, machine, kind, starts_at, ends_at, reason, refund=True, now=None):
    """Start maintenance (ends_at may be None: until someone ends it) or
    archive a machine (ends_at must be None). Returns (period, cancelled)."""
    now = now or timezone.now()
    reason = reason.strip()
    if not reason:
        raise MaintenanceError(_("A reason is required."))
    _check_actor(actor, machine)
    if starts_at < now - NOW_TOLERANCE:
        raise MaintenanceError(_("The start cannot be in the past. Choose “starting now”."))
    starts_at = max(starts_at, now)  # "starting now", sent a moment ago
    with transaction.atomic():
        machine = Machine.objects.select_for_update().get(pk=machine.pk)
        _validate(machine, kind, starts_at, ends_at, now)
        period = MachineUnavailability.objects.create(
            machine=machine,
            kind=kind,
            starts_at=starts_at,
            ends_at=ends_at,
            reason=reason,
            refund=refund,
            created_by=actor,
        )
        future, _in_progress = affected(machine, starts_at, ends_at, now)
        cancelled = _cancel(future, actor, _label(kind), reason, refund, now)
        record(
            actor=actor,
            action="machine.archive"
            if kind == MachineUnavailability.Kind.ARCHIVE
            else "machine.maintenance",
            target=period,
            after={**snapshot(period), "cancelled_bookings": cancelled},
            reason=reason,
            dormitory=machine.dormitory,
        )
    return period, cancelled


def extend(*, actor, period, ends_at, reason, refund=True, now=None):
    """Make running or planned maintenance last longer (ends_at None: until
    someone ends it). Bookings in the added time are cancelled."""
    now = now or timezone.now()
    reason = reason.strip()
    if not reason:
        raise MaintenanceError(_("A reason is required."))
    machine = period.machine
    _check_actor(actor, machine)
    with transaction.atomic():
        Machine.objects.select_for_update().get(pk=machine.pk)
        period = MachineUnavailability.objects.select_for_update().get(pk=period.pk)
        if period.kind != MachineUnavailability.Kind.MAINTENANCE:
            raise MaintenanceError(_("Only maintenance can be extended."))
        if period.ends_at is None:
            raise MaintenanceError(_("This maintenance has no end yet."))
        if period.ends_at <= now:
            raise MaintenanceError(_("This maintenance is already over."))
        if ends_at is not None and ends_at <= period.ends_at:
            raise MaintenanceError(_("The new end must be later than the current one."))
        _validate(machine, period.kind, max(period.starts_at, now), ends_at, now, exclude=period)
        before = snapshot(period)
        added_from = period.ends_at
        period.ends_at = ends_at
        period.save(update_fields=["ends_at"])
        future, _in_progress = affected(machine, added_from, ends_at, now)
        cancelled = _cancel(future, actor, _label(period.kind), reason, refund, now)
        record(
            actor=actor,
            action="machine.maintenance_extend",
            target=period,
            before=before,
            after={**snapshot(period), "cancelled_bookings": cancelled},
            reason=reason,
            dormitory=machine.dormitory,
        )
    return period, cancelled


def end_now(*, actor, period, now=None):
    """End running maintenance now: the machine can be booked from this
    moment. Planned maintenance that has not started is removed instead.
    Bookings it cancelled stay cancelled (the residents were told)."""
    now = now or timezone.now()
    machine = period.machine
    _check_actor(actor, machine)
    with transaction.atomic():
        Machine.objects.select_for_update().get(pk=machine.pk)
        period = MachineUnavailability.objects.select_for_update().get(pk=period.pk)
        if period.kind != MachineUnavailability.Kind.MAINTENANCE:
            raise MaintenanceError(_("An archived machine cannot come back."))
        if period.ends_at is not None and period.ends_at <= now:
            raise MaintenanceError(_("This maintenance is already over."))
        before = snapshot(period)
        if period.starts_at >= now:
            record(
                actor=actor,
                action="machine.maintenance_cancel",
                target=period,
                before=before,
                dormitory=machine.dormitory,
            )
            period.delete()
            return None
        period.ends_at = now
        period.save(update_fields=["ends_at"])
        record(
            actor=actor,
            action="machine.maintenance_end",
            target=period,
            before=before,
            after=snapshot(period),
            dormitory=machine.dormitory,
        )
    return period
