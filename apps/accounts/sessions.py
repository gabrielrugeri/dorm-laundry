"""How long a login lasts.

- Residents: SESSION_COOKIE_AGE (30 days), counted from their last visit.
  The session is refreshed at most once a day, so we do not write to the
  database on every request.
- Staff (managers, admins, superusers): STAFF_SESSION_SECONDS (12 hours)
  after logging in, not extended by activity: their pages show residents'
  names and rooms.
"""

from datetime import timedelta

from django.conf import settings
from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver
from django.utils import timezone

from .decorators import is_staff_member

REFRESHED_ON = "refreshed_on"


def is_staff_login(user):
    return user.is_superuser or is_staff_member(user)


@receiver(user_logged_in)
def set_session_length(sender, request, user, **kwargs):
    if is_staff_login(user):
        # A fixed end time: later requests do not move it.
        ends = timezone.now() + timedelta(seconds=settings.STAFF_SESSION_SECONDS)
        request.session.set_expiry(ends)
    else:
        request.session.set_expiry(settings.SESSION_COOKIE_AGE)
        request.session[REFRESHED_ON] = timezone.localdate().isoformat()


class KeepResidentsLoggedInMiddleware:
    """Once a day, touch a resident's session so its 30 days start again."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated and not is_staff_login(user):
            today = timezone.localdate().isoformat()
            if request.session.get(REFRESHED_ON) != today:
                request.session[REFRESHED_ON] = today  # saving resets the expiry
        return self.get_response(request)
