"""Money and upload rules in the admin area (/manage/settings/).

A sensitive setting: the change screen asks for the admin's password and a
reason, and big jumps need an extra confirmation. Every change is recorded
(apps/dorms/rules.py) and listed under the current values.
"""

from django.contrib import messages
from django.shortcuts import redirect, render
from django.utils.translation import gettext as _

from apps.audit.display import describe_changes
from apps.audit.models import AuditEvent
from apps.core.templatetags.money import rub
from apps.dorms import rules

from .forms import RulesForm
from .views import admin_required

HISTORY_LENGTH = 20


def _shown(name, value):
    """A rule's value in plain words."""
    if name == "credit_limit" and value is None:
        return _("no limit")
    if name == "credit_limit" and value == 0:
        return _("no debt allowed")
    return rub(value) if name in rules.MONEY_FIELDS else str(value)


@admin_required
def settings_page(request):
    current = rules.current()
    history = (
        AuditEvent.objects.filter(action="settings.change")
        .select_related("actor")
        .order_by("-created_at")[:HISTORY_LENGTH]
    )
    context = {
        "rows": [
            (rules.LABELS[name], _shown(name, getattr(current, name))) for name in rules.FIELDS
        ],
        "history": [(event, describe_changes(event)) for event in history],
    }
    return render(request, "manage/settings.html", context)


@admin_required
def settings_change(request):
    current = rules.current()
    form = RulesForm(request.POST or None, user=request.user, current=current)
    if request.method == "POST" and form.is_valid():
        rules.change_settings(
            actor=request.user, values=form.values(), reason=form.cleaned_data["reason"]
        )
        messages.success(request, _("The rules were changed. They apply from now on."))
        return redirect("manage:settings")
    big = [
        (
            rules.LABELS[name],
            _shown(name, getattr(current, name)),
            _shown(name, form.values()[name]),
        )
        for name in form.big
    ]
    return render(request, "manage/settings_change.html", {"form": form, "big": big})
