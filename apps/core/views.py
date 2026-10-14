from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect

from apps.accounts.decorators import is_staff_member
from apps.bookings.views import grid
from apps.keylog.views import schedule


@login_required
def home(request):
    """Residents see the availability grid; staff go to their own start page."""
    if is_staff_member(request.user):
        return redirect("core:staff_home")
    return grid(request)


def staff_home(request):
    """Managers and admins start on today's key schedule."""
    return schedule(request)
