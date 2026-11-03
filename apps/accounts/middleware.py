"""A resident who logged in with the first-time PIN (from the date of birth)
must choose their own PIN before anything else (apps/accounts/initial_pins.py)."""

from django.shortcuts import redirect
from django.urls import reverse

# Pages that stay reachable meanwhile: choosing the PIN, logging out, the
# language and colours of that page, and what the installed app needs.
ALLOWED = (
    "accounts:change_pin",
    "accounts:logout",
    "accounts:set_language",
    "accounts:set_theme",
    "core:manifest",
    "core:service_worker",
    "core:offline",
    "core:healthz",
)


class ForcePinChangeMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            resident = getattr(user, "resident", None)
            if resident is not None and resident.must_change_pin:
                allowed = {reverse(name) for name in ALLOWED}
                if request.path not in allowed and not request.path.startswith("/static/"):
                    return redirect("accounts:change_pin")
        return self.get_response(request)
