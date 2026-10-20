"""Admin area (/manage/): our own pages for the admin role, scoped to the
admin's dormitory and usable on phones. Later stages add residents, imports,
machines, settings and receipts here."""

from datetime import date

from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import render

from apps.accounts import roles
from apps.accounts.decorators import role_required
from apps.audit.actions import label
from apps.audit.models import AuditEvent

admin_required = role_required(roles.ADMIN)

EVENTS_PER_PAGE = 50


@admin_required
def index(request):
    return render(request, "manage/index.html")


def _date(value):
    try:
        return date.fromisoformat(value or "")
    except ValueError:
        return None


@admin_required
def audit_log(request):
    """Every recorded admin action in this dormitory, newest first, with filters."""
    dormitory = request.dormitory
    events = AuditEvent.objects.filter(
        # Events of this dormitory, plus dormitory-less events by its own staff.
        Q(dormitory=dormitory)
        | Q(dormitory__isnull=True, actor__staff_profile__dormitory=dormitory)
    ).select_related("actor")

    action = request.GET.get("action", "")
    if action:
        events = events.filter(action=action)
    query = request.GET.get("q", "").strip()
    if query:
        events = events.filter(
            Q(target_repr__icontains=query)
            | Q(reason__icontains=query)
            | Q(actor__username__icontains=query)
        )
    date_from, date_to = _date(request.GET.get("from")), _date(request.GET.get("to"))
    if date_from:
        events = events.filter(created_at__date__gte=date_from)
    if date_to:
        events = events.filter(created_at__date__lte=date_to)

    actions = sorted(
        {
            code
            for code in AuditEvent.objects.filter(dormitory=dormitory).values_list(
                "action", flat=True
            )
        },
        key=lambda code: str(label(code)),
    )
    page = Paginator(events, EVENTS_PER_PAGE).get_page(request.GET.get("page"))
    context = {
        "page": page,
        "actions": [(code, label(code)) for code in actions],
        "filters": {
            "action": action,
            "q": query,
            "from": date_from.isoformat() if date_from else "",
            "to": date_to.isoformat() if date_to else "",
        },
    }
    return render(request, "manage/audit_log.html", context)
