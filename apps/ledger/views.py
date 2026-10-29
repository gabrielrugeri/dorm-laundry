from django.core.paginator import Paginator
from django.shortcuts import render

from apps.accounts.decorators import resident_required

from .history import display_lines
from .models import LedgerEntry

# Display lines per page (a booking's per-slot entries make one line).
LINES_PER_PAGE = 20


@resident_required
def balance(request):
    """The resident's balance and their own history, newest first, one line
    per booking (see apps/ledger/history.py)."""
    resident = request.user.resident
    entries = LedgerEntry.objects.filter(resident=resident).select_related(
        "booking__machine", "booking__slot"
    )
    page = Paginator(display_lines(entries), LINES_PER_PAGE).get_page(request.GET.get("page"))
    context = {
        "resident": resident,
        "balance": LedgerEntry.objects.balance(resident),
        "page": page,
    }
    return render(request, "ledger/balance.html", context)
