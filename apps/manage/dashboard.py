"""Numbers for the admin dashboard (/manage/): plain counts and sums from the
ledger, receipts and bookings of one dormitory. No charting library: the
template draws the charts as SVG from these numbers.

"Money received" means money that came in: payments from receipts and those
recorded by admins (including taken-back payments), minus voided receipts.
Bookings, refunds and corrections are not money received.

Occupancy: booked machine-slots divided by the machine-slots there were
(active machines × active slots × days). Machines under maintenance
(Stage 2) will have to be left out of the second number.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, time, timedelta

from django.db.models import Count, Q, Sum, Value
from django.db.models.functions import Coalesce

from apps.accounts.models import Resident
from apps.bookings.models import Booking
from apps.dorms.models import Machine, TimeSlot
from apps.ledger.models import LedgerEntry
from apps.receipts.models import Receipt

HISTORY_WEEKS = 8
RECEIVED = Q(kind=LedgerEntry.Kind.CREDIT) | Q(kind=LedgerEntry.Kind.REVERSAL)


def _start(day, tz):
    return datetime.combine(day, time.min, tzinfo=tz)


def _month_start(day):
    return day.replace(day=1)


def _previous_month_start(day):
    return (_month_start(day) - timedelta(days=1)).replace(day=1)


def money_received(dormitory, first_day, end_day):
    """Money received from first_day up to (not including) end_day, local days."""
    tz = dormitory.tzinfo
    total = LedgerEntry.objects.filter(
        RECEIVED,
        resident__dormitory=dormitory,
        created_at__gte=_start(first_day, tz),
        created_at__lt=_start(end_day, tz),
    ).aggregate(total=Sum("amount"))["total"]
    return total or 0


def _booked(dormitory, first_day, end_day):
    return Booking.objects.filter(
        machine__dormitory=dormitory, date__gte=first_day, date__lt=end_day
    ).exclude(status__in=Booking.CANCELLED_STATUSES)


def occupancy(dormitory, first_day, end_day):
    """Share of machine-slots booked, 0..1 (None when there were none)."""
    machines = Machine.objects.filter(dormitory=dormitory, active=True).count()
    slots = TimeSlot.objects.filter(dormitory=dormitory, active=True).count()
    possible = machines * slots * (end_day - first_day).days
    if not possible:
        return None
    return _booked(dormitory, first_day, end_day).count() / possible


@dataclass
class Tiles:
    received_this_month: int
    received_last_month: int
    debt_total: int
    debtors: int
    occupancy_this_week: float | None
    voided_count: int
    voided_total: int


def tiles(dormitory, today):
    month = _month_start(today)
    last_month = _previous_month_start(today)
    tomorrow = today + timedelta(days=1)
    balances = (
        Resident.objects.filter(dormitory=dormitory, anonymized_at__isnull=True)
        .annotate(balance=Coalesce(Sum("ledger_entries__amount"), Value(0)))
        .filter(balance__lt=0)
        .values_list("balance", flat=True)
    )
    monday = today - timedelta(days=today.weekday())
    voided = Receipt.objects.filter(
        resident__dormitory=dormitory,
        status=Receipt.Status.VOIDED,
        voided_at__gte=_start(month, dormitory.tzinfo),
    ).aggregate(count=Count("id"), total=Sum("amount"))
    return Tiles(
        received_this_month=money_received(dormitory, month, tomorrow),
        received_last_month=money_received(dormitory, last_month, month),
        debt_total=-sum(balances),
        debtors=len(balances),
        occupancy_this_week=occupancy(dormitory, monday, monday + timedelta(days=7)),
        voided_count=voided["count"],
        voided_total=voided["total"] or 0,
    )


def history_start(today, weeks=HISTORY_WEEKS):
    """Monday `weeks` weeks ago: charts cover whole weeks up to this week."""
    return today - timedelta(days=today.weekday(), weeks=weeks - 1)


def heatmap(dormitory, today, weeks=HISTORY_WEEKS):
    """{"slots": [...], "rows": [(weekday 0..6, [share or None per slot])]} for
    the past `weeks` weeks up to yesterday (today is not over yet)."""
    first = history_start(today, weeks)
    slots = list(TimeSlot.objects.filter(dormitory=dormitory, active=True).order_by("start_time"))
    machines = Machine.objects.filter(dormitory=dormitory, active=True).count()
    days_per_weekday = defaultdict(int)
    day = first
    while day < today:
        days_per_weekday[day.weekday()] += 1
        day += timedelta(days=1)
    booked = defaultdict(int)
    for booking_day, slot_id in _booked(dormitory, first, today).values_list("date", "slot_id"):
        booked[(booking_day.weekday(), slot_id)] += 1
    rows = []
    for weekday in range(7):
        possible = machines * days_per_weekday[weekday]
        rows.append(
            (
                weekday,
                [booked[(weekday, slot.id)] / possible if possible else None for slot in slots],
            )
        )
    return {"slots": slots, "rows": rows}


def received_per_week(dormitory, today, weeks=HISTORY_WEEKS):
    """[(monday, money received that week)] for the past `weeks` weeks."""
    first = history_start(today, weeks)
    return [
        (
            first + timedelta(weeks=n),
            money_received(dormitory, first + timedelta(weeks=n), first + timedelta(weeks=n + 1)),
        )
        for n in range(weeks)
    ]


def usage_per_machine(dormitory, today, weeks=HISTORY_WEEKS):
    """[(machine, booked slots)] over the past `weeks` weeks up to yesterday."""
    first = history_start(today, weeks)
    counts = dict(
        _booked(dormitory, first, today)
        .values("machine")
        .annotate(n=Count("id"))
        .values_list("machine", "n")
    )
    machines = Machine.objects.filter(dormitory=dormitory).order_by("number")
    return [
        (machine, counts.get(machine.id, 0))
        for machine in machines
        if machine.active or counts.get(machine.id)
    ]
