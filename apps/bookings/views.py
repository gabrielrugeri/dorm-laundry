from datetime import date, timedelta

from django.contrib import messages
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
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


@resident_required
def grid(request):
    """Availability grid: free machines per slot, one day at a time."""
    dormitory = request.dormitory
    days = availability.booking_days(dormitory)
    day = _chosen_day(request, days)
    context = {
        "days": days,
        "day": day,
        "rows": availability.day_availability(dormitory, request.user.resident, day),
    }
    # htmx day tabs only need the grid itself, not the whole page.
    if request.headers.get("HX-Request"):
        return render(request, "bookings/_day_grid.html", context)
    return render(request, "bookings/grid.html", context)


@resident_required
def book(request, day, slot_id):
    """Choose a machine and how many slots, then book through the service."""
    dormitory = request.dormitory
    resident = request.user.resident
    slot = get_object_or_404(TimeSlot, pk=slot_id, dormitory=dormitory, active=True)
    context = {"day": day, "slot": slot, "price": dormitory.price_per_slot}

    now = timezone.now()
    starts_at, _ends_at = slot.bounds(day)
    if day not in availability.booking_days(dormitory, now) or starts_at <= now:
        context["unavailable"] = services.OutsideBookingWindow.message
        return render(request, "bookings/book.html", context)

    runs, slots = availability.free_runs(dormitory, day, slot)
    form = BookingForm(runs, slots, data=request.POST or None)
    if request.method == "POST" and form.is_valid():
        count = form.cleaned_data["count"]
        try:
            bookings = services.book_slots(
                resident, form.cleaned_data["machine"], day, slots[:count]
            )
        except services.BookingError as error:
            form.add_error(None, error.message)
        else:
            messages.success(request, _("Your booking is confirmed."))
            return redirect("bookings:detail", group_id=bookings[0].group_id)

    context.update(
        form=form,
        fully_booked=not runs,
        balance=LedgerEntry.objects.balance(resident),
    )
    return render(request, "bookings/book.html", context)


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
