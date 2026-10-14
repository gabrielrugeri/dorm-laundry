from datetime import date, timedelta

from django.contrib import messages
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts.decorators import staff_required
from apps.bookings.availability import local_today
from apps.bookings.models import Booking

from . import schedule as key_schedule
from . import services

ACTIONS = {
    "take": services.take_key,
    "return": services.return_key,
    "undo": services.undo_last,
}


def _staff_days(dormitory):
    """Yesterday, today and tomorrow."""
    today = local_today(dormitory)
    return [today + timedelta(days=n) for n in (-1, 0, 1)]


def _chosen_day(value, days):
    try:
        day = date.fromisoformat(value or "")
    except ValueError:
        return days[1]
    return day if day in days else days[1]


def _render_schedule(request, day):
    dormitory = request.dormitory
    now = timezone.now()
    context = {
        "days": _staff_days(dormitory),
        "day": day,
        "rows": key_schedule.day_rows(dormitory, day, now),
        "keys_out": key_schedule.keys_out(dormitory, now),
    }
    template = (
        "keylog/_schedule.html" if request.headers.get("HX-Request") else "keylog/schedule.html"
    )
    return render(request, template, context)


@staff_required
def schedule(request):
    """The manager's start page: today's bookings and who has which key."""
    days = _staff_days(request.dormitory)
    return _render_schedule(request, _chosen_day(request.GET.get("day"), days))


@staff_required
@require_POST
def key_action(request, group_id, action):
    """'Key taken', 'Key returned' or 'Undo' for one booking group."""
    if action not in ACTIONS:
        raise Http404
    if not Booking.objects.filter(group_id=group_id, machine__dormitory=request.dormitory).exists():
        raise Http404
    kwargs = {"actor": request.user}
    if action != "undo":
        kwargs["note"] = request.POST.get("note", "")
    try:
        ACTIONS[action](group_id, **kwargs)
    except services.KeyActionError as error:
        messages.error(request, error.message)

    day = _chosen_day(request.POST.get("day"), _staff_days(request.dormitory))
    if request.headers.get("HX-Request"):
        return _render_schedule(request, day)
    return redirect(f"{reverse('core:staff_home')}?day={day.isoformat()}")
