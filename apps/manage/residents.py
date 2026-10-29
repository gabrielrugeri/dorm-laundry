"""Residents in the admin area: list, profile and actions.

Follows the Admin UI principles (docs/CLAUDE.md): plain words, one primary
action per screen, confirmation for destructive actions, and actions that
are not allowed have no button. Every write goes through a service.
"""

import csv
import re
from datetime import timedelta

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q, Sum, Value
from django.db.models.functions import Coalesce
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import formats, timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.accounts import services as resident_services
from apps.accounts.activation import activation_url
from apps.accounts.models import Resident
from apps.audit.services import record
from apps.bookings import services as booking_services
from apps.bookings.groups import get_group_or_404, resident_groups
from apps.bookings.models import Booking
from apps.keylog.models import KeyLog
from apps.ledger import services as ledger_services
from apps.ledger.models import LedgerEntry

from .forms import (
    CancelBookingForm,
    ConfirmDebtForm,
    CorrectionForm,
    PaymentForm,
    ResidentForm,
)
from .views import admin_required

RESIDENTS_PER_PAGE = 50
RECENT_PAYMENTS = 5
FILTERS = ("active", "debt", "off")


def room_key(room):
    """Natural order for rooms: numbers compare as numbers, so
    210 < 301-1 < 301-2 < 1010. Rooms starting with letters come after, and
    an empty room (erased residents) last."""
    parts = re.findall(r"\d+|\D+", room or "")
    return (not parts, [(0, int(p), "") if p.isdigit() else (1, 0, p.lower()) for p in parts])


def _name_key(resident):
    return (resident.is_anonymized, resident.full_name.lower())


# ?sort=room|name|balance, with a leading "-" for the other direction.
SORTS = {
    "room": lambda r: (room_key(r.room), _name_key(r)),
    "name": lambda r: (_name_key(r), room_key(r.room)),
    "balance": lambda r: (r.balance, room_key(r.room), _name_key(r)),
}


def _resident(request, pk):
    """A resident of the admin's own dormitory, or 404."""
    return get_object_or_404(
        Resident.objects.select_related("user"), pk=pk, dormitory=request.dormitory
    )


def _balance(resident):
    return LedgerEntry.objects.balance(resident)


# --- List ----------------------------------------------------------------------------


@admin_required
def resident_list(request):
    show = request.GET.get("show", "active")
    show = show if show in FILTERS else "active"
    query = request.GET.get("q", "").strip()
    residents = (
        Resident.objects.filter(dormitory=request.dormitory)
        .select_related("user")
        .annotate(balance=Coalesce(Sum("ledger_entries__amount"), Value(0)))
    )
    if show == "active":
        residents = residents.filter(user__is_active=True)
    elif show == "off":
        residents = residents.filter(user__is_active=False)
    else:
        residents = residents.filter(balance__lt=0)
    if query:
        residents = residents.filter(
            Q(full_name__icontains=query)
            | Q(room__icontains=query)
            | Q(student_code__iexact=query, anonymized_at__isnull=True)
        )
    sort = request.GET.get("sort", "room")
    field = sort.removeprefix("-")
    if field not in SORTS:
        sort = field = "room"
    # Sorted in Python: natural room order is hard in SQL, and a dormitory
    # has a few hundred residents at most.
    residents = sorted(residents, key=SORTS[field], reverse=sort.startswith("-"))
    page = Paginator(residents, RESIDENTS_PER_PAGE).get_page(request.GET.get("page"))
    columns = [
        (name, label, f"-{name}" if sort == name else name, sort.removeprefix("-") == name)
        for name, label in (("room", _("Room")), ("name", _("Name")), ("balance", _("Balance")))
    ]
    context = {
        "page": page,
        "show": show,
        "query": query,
        "sort": sort,
        "descending": sort.startswith("-"),
        "columns": columns,
    }
    return render(request, "manage/residents/list.html", context)


# --- Profile -------------------------------------------------------------------------


def _payment_history(resident):
    """All money movements, newest first, each with the balance after it."""
    entries = list(
        LedgerEntry.objects.filter(resident=resident)
        .select_related("booking__machine", "booking__slot")
        .order_by("created_at", "id")
    )
    running = 0
    for entry in entries:
        running += entry.amount
        entry.balance_after = running
    return list(reversed(entries))


@admin_required
def resident_detail(request, pk):
    resident = _resident(request, pk)
    now = timezone.now()
    balance = _balance(resident)
    groups = resident_groups(
        resident,
        Booking.objects.filter(resident=resident, date__gte=now.date() - timedelta(days=90)),
    )
    upcoming = [g for g in groups if any(b.ends_at > now for b in g.active_bookings())]
    history = _payment_history(resident)
    context = {
        "resident": resident,
        "balance": balance,
        "debt_since": LedgerEntry.objects.debt_since(resident) if balance < 0 else None,
        "upcoming": upcoming,
        "can_cancel": {
            g.group_id for g in upcoming if any(b.starts_at > now for b in g.active_bookings())
        },
        "recent_payments": [e for e in history if e.kind == LedgerEntry.Kind.CREDIT][
            :RECENT_PAYMENTS
        ],
        "history": history,
        "past_bookings": [g for g in reversed(groups) if g not in upcoming],
        "key_logs": KeyLog.objects.filter(booking__resident=resident)
        .select_related("booking__machine")
        .order_by("-booking__starts_at")[:20],
        "can_delete": not resident_services.has_history(resident),
    }
    return render(request, "manage/residents/detail.html", context)


# --- Add and edit --------------------------------------------------------------------


@admin_required
def resident_add(request):
    form = ResidentForm(request.POST or None, dormitory=request.dormitory)
    if request.method == "POST" and form.is_valid():
        resident = resident_services.create_resident(
            actor=request.user, dormitory=request.dormitory, **form.cleaned_data
        )
        messages.success(
            request, _("Resident added. Give them a login link so they can choose a PIN.")
        )
        return redirect("manage:resident", pk=resident.pk)
    return render(
        request,
        "manage/residents/form.html",
        {"form": form, "title": _("Add a resident"), "submit": _("Add resident")},
    )


@admin_required
def resident_edit(request, pk):
    resident = _resident(request, pk)
    if resident.is_anonymized:
        raise Http404
    initial = {f: getattr(resident, f) for f in ("full_name", "room", "student_code")}
    form = ResidentForm(
        request.POST or None, dormitory=request.dormitory, resident=resident, initial=initial
    )
    if request.method == "POST" and form.is_valid():
        resident_services.update_resident(
            actor=request.user, resident=resident, **form.cleaned_data
        )
        messages.success(request, _("Details saved."))
        return redirect("manage:resident", pk=resident.pk)
    return render(
        request,
        "manage/residents/form.html",
        {"form": form, "resident": resident, "title": _("Change details"), "submit": _("Save")},
    )


# --- Money ---------------------------------------------------------------------------


def _money_form(request, pk, form_class, kind, title, submit, done):
    resident = _resident(request, pk)
    if resident.is_anonymized:
        raise Http404
    form = form_class(request.POST or None)
    if request.method == "POST" and form.is_valid():
        ledger_services.add_manual_entry(
            actor=request.user,
            resident=resident,
            kind=kind,
            amount=form.cleaned_data["amount"],
            note=form.cleaned_data["note"],
        )
        messages.success(request, done)
        return redirect("manage:resident", pk=resident.pk)
    context = {
        "form": form,
        "resident": resident,
        "balance": _balance(resident),
        "title": title,
        "submit": submit,
    }
    return render(request, "manage/residents/form.html", context)


@admin_required
def resident_payment(request, pk):
    return _money_form(
        request,
        pk,
        PaymentForm,
        LedgerEntry.Kind.CREDIT,
        _("Record a payment"),
        _("Record payment"),
        _("Payment recorded."),
    )


@admin_required
def resident_correction(request, pk):
    return _money_form(
        request,
        pk,
        CorrectionForm,
        LedgerEntry.Kind.ADJUSTMENT,
        _("Correct the balance"),
        _("Save correction"),
        _("Balance corrected."),
    )


# --- Login -------------------------------------------------------------------------


@admin_required
@require_POST
def resident_login_link(request, pk):
    """A one-time login link. Shown once; never stored."""
    resident = _resident(request, pk)
    if resident.is_anonymized or not resident.user.is_active:
        raise Http404
    record(actor=request.user, action="resident.activation_link", target=resident)
    context = {"resident": resident, "link": activation_url(request, resident.user)}
    return render(request, "manage/residents/login_link.html", context)


@admin_required
def resident_reset_pin(request, pk):
    resident = _resident(request, pk)
    if resident.is_anonymized or not resident.user.is_active:
        raise Http404
    if request.method == "POST":
        resident.user.set_unusable_password()
        resident.user.save(update_fields=["password"])
        record(actor=request.user, action="resident.pin_reset", target=resident)
        context = {
            "resident": resident,
            "link": activation_url(request, resident.user),
            "after_reset": True,
        }
        return render(request, "manage/residents/login_link.html", context)
    return _confirm(
        request,
        resident,
        title=_("Reset PIN"),
        text=_(
            "The current PIN stops working at once. You then get a login link to give to the resident."
        ),
        submit=_("Reset PIN"),
    )


# --- Access, erase, delete -----------------------------------------------------------


def _confirm(request, resident, *, title, text, submit, debt_form=None, danger=True):
    balance = _balance(resident)
    context = {
        "resident": resident,
        "balance": balance,
        "owed": -balance if balance < 0 else 0,
        "title": title,
        "text": text,
        "submit": submit,
        "debt_form": debt_form,
        "danger": danger,
    }
    return render(request, "manage/residents/confirm.html", context)


def _debt_action(request, pk, *, service, title, text, submit, done, allowed):
    resident = _resident(request, pk)
    if not allowed(resident):
        raise Http404
    owes = _balance(resident) < 0
    debt_form = ConfirmDebtForm(request.POST or None) if owes else None
    if request.method == "POST" and (debt_form is None or debt_form.is_valid()):
        service(actor=request.user, resident=resident, confirm_debt=owes)
        messages.success(request, done)
        return redirect("manage:resident", pk=resident.pk)
    return _confirm(request, resident, title=title, text=text, submit=submit, debt_form=debt_form)


@admin_required
def resident_deactivate(request, pk):
    return _debt_action(
        request,
        pk,
        service=resident_services.deactivate,
        title=_("Turn off access"),
        text=_(
            "The resident can no longer log in or book. Their history stays. You can turn access back on later."
        ),
        submit=_("Turn off access"),
        done=_("Access turned off."),
        allowed=lambda r: r.user.is_active and not r.is_anonymized,
    )


@admin_required
@require_POST
def resident_reactivate(request, pk):
    resident = _resident(request, pk)
    if resident.user.is_active or resident.is_anonymized:
        raise Http404
    resident_services.reactivate(actor=request.user, resident=resident)
    messages.success(request, _("Access turned back on."))
    return redirect("manage:resident", pk=resident.pk)


@admin_required
def resident_erase(request, pk):
    return _debt_action(
        request,
        pk,
        service=resident_services.anonymize,
        title=_("Erase personal data"),
        text=_(
            "Name, room and student code are erased everywhere, also in the change history, "
            "and access is turned off. Bookings and payments stay so the money still adds up. "
            "This cannot be undone."
        ),
        submit=_("Erase personal data"),
        done=_("Personal data erased."),
        allowed=lambda r: not r.is_anonymized,
    )


@admin_required
def resident_delete(request, pk):
    resident = _resident(request, pk)
    if resident_services.has_history(resident):
        raise Http404  # no button for it either
    if request.method == "POST":
        resident_services.delete_resident(actor=request.user, resident=resident)
        messages.success(request, _("Resident deleted."))
        return redirect("manage:residents")
    return _confirm(
        request,
        resident,
        title=_("Delete resident"),
        text=_(
            "This resident has no bookings or payments, so they can be deleted completely. This cannot be undone."
        ),
        submit=_("Delete resident"),
    )


# --- Bookings ------------------------------------------------------------------------


@admin_required
def resident_cancel_booking(request, pk, group_id):
    resident = _resident(request, pk)
    group = get_group_or_404(resident, group_id)
    now = timezone.now()
    cancellable = [b for b in group.active_bookings() if b.starts_at > now]
    if not cancellable:
        raise Http404
    form = CancelBookingForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            booking_services.cancel_group(
                group.group_id,
                actor=request.user,
                reason=form.cleaned_data["reason"],
                full_refund=form.cleaned_data["refund"] == "full",
            )
        except booking_services.BookingError as error:
            messages.error(request, error.message)
        else:
            messages.success(request, _("Booking cancelled. The resident sees your reason."))
        return redirect("manage:resident", pk=resident.pk)
    rule_refund = sum(b.price_rub for b in cancellable if booking_services.refund_due(b, now))
    context = {
        "resident": resident,
        "group": group,
        "form": form,
        "rule_refund": rule_refund,
        "full_refund": sum(b.price_rub for b in cancellable),
    }
    return render(request, "manage/residents/cancel_booking.html", context)


# --- Export --------------------------------------------------------------------------


def _safe(text):
    """Stop spreadsheets from running a cell as a formula (CSV injection)."""
    text = str(text)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


@admin_required
def resident_history_csv(request, pk):
    """The payment history as a spreadsheet (CSV, opens in Excel)."""
    resident = _resident(request, pk)
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="payment-history.csv"'
    response.write("﻿")  # so Excel opens the Cyrillic text correctly
    writer = csv.writer(response, delimiter=";")
    writer.writerow([_("Date"), _("What"), _("Amount, ₽"), _("Balance after, ₽"), _("Comment")])
    for entry in reversed(_payment_history(resident)):
        local = timezone.localtime(entry.created_at)
        writer.writerow(
            [
                formats.date_format(local, "d.m.Y H:i"),
                _safe(str(entry.get_kind_display()).capitalize()),
                entry.amount,
                entry.balance_after,
                _safe(entry.note),
            ]
        )
    return response
