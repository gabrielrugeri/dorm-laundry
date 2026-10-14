from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from apps.accounts.decorators import is_staff_member, staff_required
from apps.bookings.views import grid


@login_required
def home(request):
    """Residents see the availability grid; staff go to their own start page."""
    if is_staff_member(request.user):
        return redirect("core:staff_home")
    return grid(request)


@staff_required
def staff_home(request):
    return render(request, "core/staff_home.html")
