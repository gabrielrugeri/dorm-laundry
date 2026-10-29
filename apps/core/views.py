from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db import DatabaseError, connection
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render

from apps.accounts import roles
from apps.accounts.decorators import is_staff_member, staff_required
from apps.bookings.views import grid
from apps.keylog.views import schedule


@login_required
def home(request):
    """Residents see the availability grid; staff go to their own start page."""
    if is_staff_member(request.user):
        return redirect("core:staff_home")
    return grid(request)


@staff_required
def staff_home(request):
    """Managers and admins start on today's key schedule. While key handling
    is on hold, admins start in the admin area and managers see a short note."""
    if settings.KEYS_ENABLED:
        return schedule(request)
    if roles.has_role(request.user, roles.ADMIN):
        return redirect("manage:index")
    return render(request, "core/staff_unavailable.html")


def healthz(request):
    """For the hosting platform's health check: 200 when the app and the
    database answer, 503 otherwise. No login, no personal data."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except DatabaseError:
        return JsonResponse({"status": "database unavailable"}, status=503)
    return JsonResponse({"status": "ok"})


def robots_txt(request):
    """The demo asks search engines to stay away entirely; a real instance
    only keeps them out of the login and staff pages."""
    if settings.DEMO_MODE:
        lines = ["User-agent: *", "Disallow: /"]
    else:
        lines = ["User-agent: *", "Disallow: /account/", "Disallow: /manage/", "Disallow: /staff/"]
    return HttpResponse("\n".join(lines) + "\n", content_type="text/plain")
