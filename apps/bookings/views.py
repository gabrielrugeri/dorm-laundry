import uuid
from datetime import date, timedelta

from django.contrib import messages
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import ngettext

from apps.accounts.decorators import resident_required
from apps.dorms.models import TimeSlot
from apps.ledger.models import LedgerEntry

from . import availability, ics, services
from .forms import BookingForm
from .groups import get_group_or_404, resident_groups
from .models import Booking

# How far back "My bookings" shows past and cancelled bookings.
HISTORY_DAYS = 30


def _chosen_day(request, days):
    """The ?day=YYYY-MM-DD parameter if it is a bookable day, else today."""
    try:
        day = date.fromisoformat(request.GET.get("day", ""))
    except ValueError:
        return days[0]
    return day if day in days else days[0]


def _chosen_length(request, dormitory):
    """The ?length=N parameter (slots in a row), between 1 and the longest
    possible run; 1 if missing or invalid."""
    longest = max(availability.max_length(dormitory), 1)
    try:
        length = int(request.GET.get("length", 1))
    except ValueError:
        return 1
    return min(max(length, 1), longest)


@resident_required
def grid(request):
    """Availability grid: for the chosen day and length (slots in a row), the
    start times where at least one machine is free for the whole length."""
    dormitory = request.dormitory
    resident = request.user.resident
    days = availability.booking_days(dormitory)
    day = _chosen_day(request, days)
    length = _chosen_length(request, dormitory)
    own = Booking.objects.filter(resident=resident, date=day).exclude(
        status=Booking.Status.CANCELLED
    )
    context = {
        "days": days,
        "day": day,
        "length": length,
        "lengths": range(1, availability.max_length(dormitory) + 1),
        "slot_hours": availability.slot_hours(dormitory),
        "options": availability.start_options(dormitory, day, length),
        "own_groups": resident_groups(resident, own),
    }
    # htmx tabs only need the grid itself, not the whole page.
    if request.headers.get("HX-Request"):
        return render(request, "bookings/_day_grid.html", context)
    return render(request, "bookings/grid.html", context)


@resident_required
def book(request, day, slot_id):
    """Tick one or more machines for the chosen start and length, then book
    them all through the service."""
    dormitory = request.dormitory
    resident = request.user.resident
    slot = get_object_or_404(TimeSlot, pk=slot_id, dormitory=dormitory, active=True)
    length = _chosen_length(request, dormitory)
    run = availability.following_slots(dormitory, slot)[:length]
    context = {
        "day": day,
        "slot": slot,
        "run": run,
        "length": length,
        "price": dormitory.price_per_slot,
        "price_per_machine": dormitory.price_per_slot * len(run),
    }

    now = timezone.now()
    starts_at, _ends_at = slot.bounds(day)
    if day not in availability.booking_days(dormitory, now) or starts_at <= now:
        context["unavailable"] = services.OutsideBookingWindow.message
        return render(request, "bookings/book.html", context)
    if len(run) < length:
        context["unavailable"] = _("There are not enough time slots left in the day.")
        return render(request, "bookings/book.html", context)

    choices = availability.machine_choices(dormitory, day, run)
    # Bind on every POST, even an empty one (no machine ticked), so the error shows.
    form = BookingForm(choices, data=request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        try:
            groups = services.book_machines(resident, form.cleaned_data["machines"], day, run)
        except services.BookingError as error:
            form.add_error(None, error.message)
        else:
            messages.success(request, _("Your booking is confirmed."))
            ids = "&".join(f"g={group[0].group_id}" for group in groups)
            return redirect(f"{reverse('bookings:confirmed')}?{ids}")

    context.update(form=form, balance=LedgerEntry.objects.balance(resident))
    return render(request, "bookings/book.html", context)


@resident_required
def confirmed(request):
    """What was just booked: one item per machine (?g=<group id>&g=...)."""
    ids = []
    for value in request.GET.getlist("g"):
        try:
            ids.append(uuid.UUID(value))
        except ValueError:
            continue
    resident = request.user.resident
    groups = resident_groups(resident, Booking.objects.filter(resident=resident, group_id__in=ids))
    if not groups:
        raise Http404
    return render(request, "bookings/confirmed.html", {"groups": groups})


@resident_required
def group_detail(request, group_id):
    """One booking (all slots booked together); shown after booking."""
    group = get_group_or_404(request.user.resident, group_id)
    now = timezone.now()
    can_cancel = any(b.starts_at > now for b in group.active_bookings())
    return render(request, "bookings/detail.html", {"group": group, "can_cancel": can_cancel})


@resident_required
def calendar_file(request, group_id):
    """The booking as an .ics file for the resident's calendar app."""
    group = get_group_or_404(request.user.resident, group_id)
    if group.is_cancelled:
        raise Http404
    body = ics.booking_calendar(
        group,
        request.dormitory,
        uid_domain=request.get_host().split(":")[0],
        summary=_("Laundry: %(machine)s") % {"machine": group.machine.name},
    )
    response = HttpResponse(body, content_type="text/calendar; charset=utf-8")
    filename = f"laundry-{group.day.isoformat()}.ics"
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@resident_required
def my_bookings(request):
    resident = request.user.resident
    now = timezone.now()
    since = availability.local_today(request.dormitory, now) - timedelta(days=HISTORY_DAYS)
    groups = resident_groups(resident, Booking.objects.filter(resident=resident, date__gte=since))
    upcoming = [g for g in groups if any(b.ends_at > now for b in g.active_bookings())]
    past = [g for g in reversed(groups) if g not in upcoming]
    return render(request, "bookings/my_bookings.html", {"upcoming": upcoming, "past": past})


@resident_required
def cancel(request, group_id):
    """Confirm, then cancel the slots of a booking that have not started yet."""
    group = get_group_or_404(request.user.resident, group_id)
    now = timezone.now()
    cancellable = [b for b in group.active_bookings() if b.starts_at > now]
    if not cancellable:
        messages.error(request, _("This booking can no longer be cancelled."))
        return redirect("bookings:mine")

    if request.method == "POST":
        try:
            services.cancel_group(group.group_id, actor=request.user)
        except services.BookingError as error:
            messages.error(request, error.message)
        else:
            messages.success(request, _("Your booking is cancelled."))
        return redirect("bookings:mine")

    refunds = [(b, services.refund_due(b, now)) for b in cancellable]
    hours = request.dormitory.cancellation_cutoff_hours
    context = {
        "group": group,
        "refunds": refunds,
        "refund_total": sum(b.price_rub for b, due in refunds if due),
        "cutoff_text": ngettext(
            "Cancelling at least %(hours)s hour before the start gives a refund.",
            "Cancelling at least %(hours)s hours before the start gives a refund.",
            hours,
        )
        % {"hours": hours},
    }
    return render(request, "bookings/cancel.html", context)
