"""Importing residents from a file, in the admin area.

Upload → preview (nothing written) → confirm (one transaction) → result with
the login links of the new residents who have no first-time PIN. Between
preview and confirm the admin's session keeps only what the preview showed
(`importing.stored`: codes, names, rooms, opening balances, hashed first-time
PINs), tied to their dormitory: never the uploaded file, never a date of
birth. It is removed on confirm and on cancel.
"""

import csv
import uuid

from django.contrib import messages
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.accounts import importing
from apps.accounts.activation import activation_url
from apps.accounts.models import Resident
from apps.audit.services import record

from .residents import SORTS, _safe
from .views import admin_required

SESSION_ROWS = "resident_import_rows"
SESSION_CREATED = "resident_import_created"


def _stored_rows(request, token):
    stored = request.session.get(SESSION_ROWS)
    if not stored or stored["token"] != token or stored["dormitory"] != request.dormitory.pk:
        return None
    return stored["rows"]


@admin_required
def upload(request):
    """Choose a file; it is checked and previewed, not imported yet."""
    error = None
    if request.method == "POST":
        upload_file = request.FILES.get("file")
        if upload_file is None:
            error = _("Choose a file first.")
        elif upload_file.size > importing.MAX_FILE_BYTES:
            error = _("The file is too large (more than 1 MB).")
        else:
            data = upload_file.read()
            try:
                result = importing.preview(request.dormitory, data)
            except importing.ImportFileError as exc:
                error = str(exc)
            else:
                token = uuid.uuid4().hex
                request.session[SESSION_ROWS] = {
                    "token": token,
                    "dormitory": request.dormitory.pk,
                    "rows": importing.stored(result),
                }
                return render(
                    request,
                    "manage/residents/import_preview.html",
                    {"result": result, "token": token},
                )
    return render(request, "manage/residents/import_upload.html", {"error": error})


@admin_required
@require_POST
def confirm(request):
    rows = _stored_rows(request, request.POST.get("token", ""))
    if rows is None:
        messages.error(request, _("The file is no longer available. Please choose it again."))
        return redirect("manage:resident_import")
    result, created = importing.apply(
        request.user,
        request.dormitory,
        rows=rows,
        renew_initial_pins=request.POST.get("renew_initial_pins") == "on",
    )
    del request.session[SESSION_ROWS]
    request.session[SESSION_CREATED] = [r.pk for r in created]
    changed = sum(1 for row in result.rows if row.status == importing.CHANGED)
    request.session["resident_import_summary"] = {
        "created": len(created),
        "changed": changed,
        "skipped": result.count(importing.ERROR),
        "initial_pins": len(result.new_with_pin)
        + (len(result.renewable_rows) if request.POST.get("renew_initial_pins") == "on" else 0),
        "openings": len(result.opening_rows),
    }
    return redirect("manage:resident_import_done")


@admin_required
@require_POST
def cancel(request):
    """Forget the previewed rows (and their hashed first-time PINs)."""
    request.session.pop(SESSION_ROWS, None)
    messages.success(request, _("Import cancelled. Nothing was changed."))
    return redirect("manage:residents")


def _new_residents(request):
    """New residents in room order (natural: 210 < 301-1 < 1010)."""
    ids = request.session.get(SESSION_CREATED, [])
    residents = Resident.objects.filter(
        pk__in=ids,
        dormitory=request.dormitory,
        anonymized_at__isnull=True,
        user__is_active=True,
    ).select_related("user")
    return sorted(residents, key=lambda r: SORTS["room"](r))


@admin_required
def done(request):
    summary = request.session.get("resident_import_summary")
    if summary is None:
        raise Http404
    from apps.dorms import rules

    # Only the new residents without a first-time PIN need a login link.
    needing_links = [r for r in _new_residents(request) if not r.user.has_usable_password()]
    return render(
        request,
        "manage/residents/import_done.html",
        {
            "summary": summary,
            "new_residents": needing_links,
            "initial_pin_days": rules.current().initial_pin_days,
        },
    )


@admin_required
def login_links_csv(request):
    """Login links for the residents created by the last import, one per row.
    Links are made now, recorded in the change history, and never stored."""
    residents = [r for r in _new_residents(request) if not r.user.has_usable_password()]
    if not residents:
        raise Http404
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="login-links.csv"'
    response.write("﻿")
    writer = csv.writer(response, delimiter=";")
    writer.writerow([_("Full name"), _("Room"), _("Student code"), _("Login link")])
    for resident in residents:
        record(actor=request.user, action="resident.activation_link", target=resident)
        writer.writerow(
            [
                _safe(resident.full_name),
                _safe(resident.room),
                _safe(resident.student_code),
                activation_url(request, resident.user),
            ]
        )
    return response


@admin_required
def sample_csv(request):
    """An example file to fill in (fake names)."""
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="residents-sample.csv"'
    response.write("﻿")
    writer = csv.writer(response, delimiter=";")
    writer.writerow(
        [_("Student code"), _("Full name"), _("Room"), _("Date of birth"), _("Opening balance")]
    )
    writer.writerow(["S12345", "Ivanova Maria", "214", "05.03.2004", "150"])
    writer.writerow(["S12346", "Petrov Sergei", "305", "", "-80"])
    return response
