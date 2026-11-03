"""Receipts in the admin area (/manage/receipts/): review, void, reconcile.

Receipts are trusted by default (Stage 4). Here the admin looks through them,
helped by automatic flags that never block anything, opens the file next to
the resident's balance and recent money movements, and voids a receipt that
turns out to be wrong (a mandatory reason; the money is taken back with a
reversal entry). The reconciliation report adds up every kind of money
movement per day, week, month or resident.
"""

import csv
from collections import defaultdict
from datetime import date, datetime, time, timedelta

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import formats, timezone
from django.utils.translation import gettext as _

from apps.dorms import rules
from apps.ledger.models import LedgerEntry
from apps.receipts import services
from apps.receipts.flags import flags_for
from apps.receipts.models import Receipt

from .forms import VoidReceiptForm
from .residents import _safe
from .views import admin_required

RECEIPTS_PER_PAGE = 30
STATUSES = ("all", "credited", "voided")


def _date(value):
    try:
        return date.fromisoformat(value or "")
    except ValueError:
        return None


def _local_start(day, tz):
    return datetime.combine(day, time.min, tzinfo=tz)


@admin_required
def receipt_list(request):
    dormitory = request.dormitory
    status = request.GET.get("status", "all")
    status = status if status in STATUSES else "all"
    query = request.GET.get("q", "").strip()
    flagged_only = request.GET.get("flagged") == "1"
    date_from, date_to = _date(request.GET.get("from")), _date(request.GET.get("to"))

    receipts = Receipt.objects.filter(resident__dormitory=dormitory).select_related("resident")
    if status != "all":
        receipts = receipts.filter(status=status)
    if query:
        receipts = receipts.filter(
            Q(resident__full_name__icontains=query) | Q(resident__room__icontains=query)
        )
    if date_from:
        receipts = receipts.filter(uploaded_at__gte=_local_start(date_from, dormitory.tzinfo))
    if date_to:
        receipts = receipts.filter(
            uploaded_at__lt=_local_start(date_to + timedelta(days=1), dormitory.tzinfo)
        )

    current = rules.current()
    if flagged_only:
        # Flags are computed, not stored; a dormitory has few receipts a day.
        rows = [(r, flags_for(r, current)) for r in receipts]
        rows = [(r, f) for r, f in rows if f]
        page = Paginator(rows, RECEIPTS_PER_PAGE).get_page(request.GET.get("page"))
    else:
        page = Paginator(receipts, RECEIPTS_PER_PAGE).get_page(request.GET.get("page"))
        page.object_list = [(r, flags_for(r, current)) for r in page.object_list]
    context = {
        "page": page,
        "filters": {
            "status": status,
            "q": query,
            "flagged": flagged_only,
            "from": request.GET.get("from", ""),
            "to": request.GET.get("to", ""),
        },
    }
    return render(request, "manage/receipts/list.html", context)


def _receipt(request, pk):
    return get_object_or_404(
        Receipt.objects.select_related("resident", "voided_by"),
        pk=pk,
        resident__dormitory=request.dormitory,
    )


@admin_required
def receipt_detail(request, pk):
    receipt = _receipt(request, pk)
    resident = receipt.resident
    context = {
        "receipt": receipt,
        "resident": resident,
        "balance": LedgerEntry.objects.balance(resident),
        "flags": flags_for(receipt),
        "recent": LedgerEntry.objects.filter(resident=resident)
        .select_related("booking__machine")
        .order_by("-created_at", "-id")[:10],
        "is_image": receipt.content_type.startswith("image/"),
        "stored": bool(receipt.file) and receipt.file.storage.exists(receipt.file.name),
    }
    return render(request, "manage/receipts/detail.html", context)


@admin_required
def receipt_void(request, pk):
    """Confirm, then void: the reason is required and shown to the admin
    team in the history; the resident sees the entry in their balance."""
    receipt = _receipt(request, pk)
    if receipt.status == Receipt.Status.VOIDED:
        return redirect("manage:receipt", pk=receipt.pk)
    form = VoidReceiptForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            services.void_receipt(
                receipt=receipt, actor=request.user, reason=form.cleaned_data["reason"]
            )
        except services.NotAllowed:
            raise Http404 from None
        messages.success(request, _("The receipt was voided and the money taken back."))
        return redirect("manage:receipt", pk=receipt.pk)
    context = {
        "receipt": receipt,
        "form": form,
        "balance": LedgerEntry.objects.balance(receipt.resident),
    }
    return render(request, "manage/receipts/void.html", context)


# --- Reconciliation ---------------------------------------------------------------

GROUPINGS = ("day", "week", "month", "resident")


def _column(entry):
    kind = entry.kind
    if kind == LedgerEntry.Kind.CREDIT:
        return "receipts" if entry.receipt_id else "payments"
    return {
        LedgerEntry.Kind.REVERSAL: "voided",
        LedgerEntry.Kind.ADJUSTMENT: "corrections",
        LedgerEntry.Kind.BOOKING: "bookings",
        LedgerEntry.Kind.REFUND: "refunds",
    }[kind]


def _column_labels():
    """The report's columns. Receipts and payments recorded by admins stay in
    separate columns, so each can be checked against the bank statement."""
    return [
        ("receipts", _("Receipts")),
        ("voided", _("Voided receipts")),
        ("payments", _("Payments recorded by admins")),
        ("corrections", _("Corrections")),
        ("bookings", _("Bookings")),
        ("refunds", _("Refunds")),
    ]


def reconciliation(dormitory, date_from, date_to, grouping):
    """Rows of {label, sort, receipts, voided, ..., total} and the totals row."""
    tz = dormitory.tzinfo
    entries = LedgerEntry.objects.filter(
        resident__dormitory=dormitory,
        created_at__gte=_local_start(date_from, tz),
        created_at__lt=_local_start(date_to + timedelta(days=1), tz),
    ).select_related("resident")
    rows = defaultdict(lambda: defaultdict(int))
    totals = defaultdict(int)
    for entry in entries:
        day = timezone.localtime(entry.created_at, tz).date()
        if grouping == "day":
            key = (day, formats.date_format(day, "j E Y"))
        elif grouping == "week":
            monday = day - timedelta(days=day.weekday())
            key = (
                monday,
                _("week of %(day)s") % {"day": formats.date_format(monday, "j E Y")},
            )
        elif grouping == "month":
            first = day.replace(day=1)
            key = (first, formats.date_format(first, "F Y"))
        else:
            resident = entry.resident
            name = str(_("Former resident")) if resident.is_anonymized else resident.full_name
            key = ((resident.room, name), f"{name} ({resident.room})" if resident.room else name)
        column = _column(entry)
        rows[key][column] += entry.amount
        rows[key]["total"] += entry.amount
        totals[column] += entry.amount
        totals["total"] += entry.amount
    ordered = [
        {"label": label, **values}
        for (sort, label), values in sorted(rows.items(), key=lambda i: i[0][0])
    ]
    return ordered, totals


@admin_required
def receipt_report(request):
    dormitory = request.dormitory
    today = timezone.localdate(timezone=dormitory.tzinfo)
    date_from = _date(request.GET.get("from")) or today.replace(day=1)
    date_to = _date(request.GET.get("to")) or today
    if date_to < date_from:
        date_from, date_to = date_to, date_from
    grouping = request.GET.get("by", "day")
    grouping = grouping if grouping in GROUPINGS else "day"
    rows, totals = reconciliation(dormitory, date_from, date_to, grouping)
    columns = _column_labels()

    if request.GET.get("format") == "csv":
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = (
            f'attachment; filename="money-{date_from.isoformat()}-{date_to.isoformat()}.csv"'
        )
        response.write("﻿")  # so Excel opens the Cyrillic text correctly
        writer = csv.writer(response, delimiter=";")
        writer.writerow(
            [_("Period") if grouping != "resident" else _("Resident")]
            + [str(label) for _key, label in columns]
            + [_("Total")]
        )
        for row in rows:
            writer.writerow(
                [_safe(str(row["label"]))]
                + [row.get(key, 0) for key, _l in columns]
                + [row["total"]]
            )
        writer.writerow(
            [_("Total")] + [totals.get(key, 0) for key, _l in columns] + [totals["total"]]
        )
        return response

    context = {
        "rows": [
            (row["label"], [row.get(key, 0) for key, _l in columns], row["total"]) for row in rows
        ],
        "totals": ([totals.get(key, 0) for key, _l in columns], totals.get("total", 0)),
        "columns": columns,
        "date_from": date_from,
        "date_to": date_to,
        "grouping": grouping,
    }
    return render(request, "manage/receipts/report.html", context)
