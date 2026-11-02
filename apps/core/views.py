import hashlib
import json
import logging

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db import DatabaseError, connection
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.templatetags.static import static
from django.urls import reverse
from django.utils.translation import get_language
from django.utils.translation import gettext as _
from django.views.decorators.cache import never_cache

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


# --- Installable app (PWA) ------------------------------------------------------------
# The manifest, the service worker and the offline page hold no personal data:
# they are the same for everyone, so caching them is safe.

THEME_COLOR = "#1d4ed8"
# 2: the worker leaves every non-GET request (form submissions) to the browser.
SW_REVISION = 2


def manifest(request):
    """The web app manifest: lets phones install the site like an app."""
    data = {
        "name": str(_("Dorm Laundry")),
        "short_name": str(_("Laundry")),
        "lang": get_language(),
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "background_color": "#f8fafc",
        "theme_color": THEME_COLOR,
        "icons": [
            {"src": static("icons/icon-192.png"), "sizes": "192x192", "type": "image/png"},
            {"src": static("icons/icon-512.png"), "sizes": "512x512", "type": "image/png"},
            {
                "src": static("icons/maskable-512.png"),
                "sizes": "512x512",
                "type": "image/png",
                "purpose": "maskable",
            },
        ],
    }
    return JsonResponse(data, content_type="application/manifest+json")


@never_cache
def service_worker(request):
    """Served from the site root so it may handle every page. It only keeps
    the offline page; see templates/core/sw.js."""
    precache = [reverse("core:offline"), static("css/app.css"), static("icons/icon-192.png")]
    # Raise SW_REVISION whenever sw.js changes, so installed copies update.
    version = hashlib.sha256("|".join([str(SW_REVISION), *precache]).encode()).hexdigest()[:12]
    response = render(
        request,
        "core/sw.js",
        {
            "precache": json.dumps(precache),
            "offline_url": json.dumps(precache[0]),
            "version": version,
        },
        content_type="text/javascript",
    )
    return response


def offline(request):
    """Shown by the service worker when there is no connection. It must stay
    free of personal data (it is cached), so it does not use base.html."""
    return render(request, "core/offline.html")


# --- CSRF failures ------------------------------------------------------------------

csrf_log = logging.getLogger("dorm_laundry.csrf")


def csrf_failure(request, reason=""):
    """Shown instead of Django's technical 403 page, in plain words. Also logs
    what is needed to tell a lost request body (e.g. a browser dropping a file
    upload) from a wrong or missing token. Never logs token values, cookies,
    form contents or who the user is."""
    try:
        post_fields = len(request.POST)
        file_fields = len(request.FILES)
        token_field = "csrfmiddlewaretoken" in request.POST
    except Exception:  # an unreadable body is itself the finding
        post_fields = file_fields = -1
        token_field = False
    origin = request.headers.get("Origin", "")
    csrf_log.warning(
        "CSRF failure: reason=%r method=%s path=%s content_type=%s content_length=%s "
        "post_fields=%s file_fields=%s token_field=%s csrf_cookie=%s origin_trusted=%s "
        "sec_fetch_mode=%s sec_fetch_dest=%s logged_in=%s user_agent=%r",
        reason,
        request.method,
        request.path,
        request.content_type,
        request.headers.get("Content-Length", ""),
        post_fields,
        file_fields,
        token_field,
        settings.CSRF_COOKIE_NAME in request.COOKIES,
        (origin in settings.CSRF_TRUSTED_ORIGINS or origin == f"https://{request.get_host()}")
        if origin
        else "no-origin",
        request.headers.get("Sec-Fetch-Mode", ""),
        request.headers.get("Sec-Fetch-Dest", ""),
        request.user.is_authenticated if hasattr(request, "user") else "?",
        request.headers.get("User-Agent", "")[:200],
    )
    return render(request, "core/csrf_failure.html", status=403)
