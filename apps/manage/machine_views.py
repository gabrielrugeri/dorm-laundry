"""Machines in the admin area (/manage/machines/): maintenance and archive.

Every action is a form, then a preview of what it does (the future bookings
it cancels, highlighted, and bookings in progress listed separately for the
admin to handle), with the "Refund affected residents" box ticked by
default, then one confirmation. The work itself is apps/dorms/maintenance.py.
"""

from django.contrib import messages
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import ngettext

from apps.dorms import machine_state, maintenance
from apps.dorms.models import Machine, MachineUnavailability

from .forms import ArchiveForm, ExtendForm, MaintenanceForm
from .views import admin_required

MAINT = MachineUnavailability.Kind.MAINTENANCE
ARCHIVE = MachineUnavailability.Kind.ARCHIVE


@admin_required
def machine_list(request):
    now = timezone.now()
    machines = list(Machine.objects.filter(dormitory=request.dormitory).order_by("number"))
    by_machine = machine_state.periods(machines)
    rows, archived = [], []
    for machine in machines:
        periods = by_machine.get(machine.pk, [])
        current = machine_state.current(periods, now)
        if current is not None and current.kind == ARCHIVE:
            archived.append((machine, current))
            continue
        rows.append(
            {
                "machine": machine,
                "current": current,
                "planned": machine_state.upcoming(periods, now),
            }
        )
    return render(request, "manage/machines/list.html", {"rows": rows, "archived": archived})


def _machine(request, pk):
    return get_object_or_404(Machine, pk=pk, dormitory=request.dormitory)


def _done_message(request, cancelled):
    if cancelled:
        messages.success(
            request,
            ngettext(
                "Saved. %(count)s booking was cancelled; the resident sees why.",
                "Saved. %(count)s bookings were cancelled; the residents see why.",
                cancelled,
            )
            % {"count": cancelled},
        )
    else:
        messages.success(request, _("Saved. No bookings were affected."))


def _action(request, *, machine, form, title, period_for, run, period=None):
    """Form -> preview -> confirm, shared by maintenance, extend and archive.
    `period_for(form, now)` gives (starts_at, ends_at) of the time to clear;
    `run(form, now)` does it and returns the number of cancelled bookings."""
    now = timezone.now()
    context = {"machine": machine, "form": form, "title": title, "period": period}
    if request.method == "POST" and form.is_valid():
        starts_at, ends_at = period_for(form, now)
        if request.POST.get("confirm"):
            try:
                cancelled = run(form, now)
            except maintenance.MaintenanceError as error:
                form.add_error(None, error.message)
            except maintenance.NotAllowed:
                raise Http404 from None
            else:
                _done_message(request, cancelled)
                return redirect("manage:machines")
        else:
            future, in_progress = maintenance.affected(machine, starts_at, ends_at, now)
            context.update(
                preview=True,
                starts_at=starts_at,
                ends_at=ends_at,
                future=future,
                in_progress=in_progress,
            )
    return render(request, "manage/machines/action.html", context)


@admin_required
def machine_maintenance(request, pk):
    machine = _machine(request, pk)
    form = MaintenanceForm(request.POST or None)

    def run(form, now):
        starts_at, ends_at = form.period(now)
        _period, cancelled = maintenance.take_out_of_service(
            actor=request.user,
            machine=machine,
            kind=MAINT,
            starts_at=starts_at,
            ends_at=ends_at,
            reason=form.cleaned_data["reason"],
            refund=form.cleaned_data["refund"],
            now=now,
        )
        return cancelled

    return _action(
        request,
        machine=machine,
        form=form,
        title=_("Put under maintenance"),
        period_for=lambda form, now: form.period(now),
        run=run,
    )


@admin_required
def machine_archive(request, pk):
    machine = _machine(request, pk)
    form = ArchiveForm(request.POST or None)

    def run(form, now):
        _period, cancelled = maintenance.take_out_of_service(
            actor=request.user,
            machine=machine,
            kind=ARCHIVE,
            starts_at=now,
            ends_at=None,
            reason=form.cleaned_data["reason"],
            refund=form.cleaned_data["refund"],
            now=now,
        )
        return cancelled

    return _action(
        request,
        machine=machine,
        form=form,
        title=_("Take out of use for good"),
        period_for=lambda form, now: (now, None),
        run=run,
    )


def _period(request, pk):
    return get_object_or_404(
        MachineUnavailability.objects.select_related("machine"),
        pk=pk,
        machine__dormitory=request.dormitory,
        kind=MAINT,
    )


@admin_required
def period_extend(request, pk):
    period = _period(request, pk)
    form = ExtendForm(request.POST or None)

    def run(form, now):
        _period, cancelled = maintenance.extend(
            actor=request.user,
            period=period,
            ends_at=form.new_end(),
            reason=form.cleaned_data["reason"],
            refund=form.cleaned_data["refund"],
            now=now,
        )
        return cancelled

    return _action(
        request,
        machine=period.machine,
        form=form,
        title=_("Extend maintenance"),
        period_for=lambda form, now: (max(period.ends_at or now, now), form.new_end()),
        run=run,
        period=period,
    )


@admin_required
def period_end(request, pk):
    """End running maintenance now, or remove planned maintenance."""
    period = _period(request, pk)
    planned = period.starts_at > timezone.now()
    if request.method == "POST":
        try:
            maintenance.end_now(actor=request.user, period=period)
        except maintenance.MaintenanceError as error:
            messages.error(request, error.message)
        else:
            messages.success(
                request,
                _("Planned maintenance removed.")
                if planned
                else _("Maintenance ended. The machine can be booked again."),
            )
        return redirect("manage:machines")
    return render(request, "manage/machines/end.html", {"period": period, "planned": planned})
