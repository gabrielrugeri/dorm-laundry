"""The admin dashboard (/manage/, «Обзор»): how the laundry is doing, in
plain numbers and three small charts drawn as SVG on the server."""

from django.shortcuts import render
from django.utils import formats, timezone
from django.utils.translation import gettext as _

from . import charts
from . import dashboard as data
from .views import admin_required


def _weekday_names():
    return [_("Mon"), _("Tue"), _("Wed"), _("Thu"), _("Fri"), _("Sat"), _("Sun")]


@admin_required
def dashboard(request):
    dormitory = request.dormitory
    today = timezone.localdate(timezone=dormitory.tzinfo)
    names = _weekday_names()

    heat = data.heatmap(dormitory, today)
    heat_chart = charts.heatmap(heat["rows"], heat["slots"])
    for cell in heat_chart["cells"]:
        cell["weekday_name"] = names[cell["weekday"]]
    for label in heat_chart["row_labels"]:
        label["name"] = names[label["weekday"]]

    weeks = data.received_per_week(dormitory, today)
    week_points = [(formats.date_format(monday, "j M"), amount) for monday, amount in weeks]
    machines = data.usage_per_machine(dormitory, today)

    busiest = max(
        (cell for cell in heat_chart["cells"] if cell["share"] is not None),
        key=lambda cell: cell["share"],
        default=None,
    )
    context = {
        "tiles": data.tiles(dormitory, today),
        "weeks": data.HISTORY_WEEKS,
        "heat": heat_chart,
        "heat_rows": [(names[weekday], shares) for weekday, shares in heat["rows"]],
        "heat_slots": heat["slots"],
        "busiest": busiest,
        "payments": charts.column_chart(week_points),
        "payments_total": sum(amount for _monday, amount in weeks),
        "machines": charts.bar_chart([(machine.name, n) for machine, n in machines]),
        "machines_total": sum(n for _machine, n in machines),
    }
    return render(request, "manage/dashboard.html", context)
