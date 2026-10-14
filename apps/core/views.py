from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from apps.accounts.decorators import is_staff_member, resident_required, staff_required


@login_required
def home(request):
    """Residents see the availability grid; staff go to their own start page."""
    if is_staff_member(request.user):
        return redirect("core:staff_home")
    return resident_home(request)


@resident_required
def resident_home(request):
    return render(request, "core/home.html")


@staff_required
def staff_home(request):
    return render(request, "core/staff_home.html")
