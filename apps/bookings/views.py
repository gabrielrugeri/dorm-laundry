from datetime import date

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.accounts.decorators import resident_required
from apps.dorms.models import TimeSlot
from apps.ledger.models import LedgerEntry

from . import availability, services
from .forms import BookingForm
from .groups import get_group_or_404


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
    return render(request, "bookings/detail.html", {"group": group})
