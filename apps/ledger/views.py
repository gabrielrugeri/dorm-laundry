from django.core.paginator import Paginator
from django.shortcuts import render

from apps.accounts.decorators import resident_required

from .models import LedgerEntry

ENTRIES_PER_PAGE = 20


@resident_required
def balance(request):
    """The resident's balance and their own ledger history, newest first."""
    resident = request.user.resident
    entries = LedgerEntry.objects.filter(resident=resident).select_related(
        "booking__machine", "booking__slot"
    )
    page = Paginator(entries, ENTRIES_PER_PAGE).get_page(request.GET.get("page"))
    context = {"balance": LedgerEntry.objects.balance(resident), "page": page}
    return render(request, "ledger/balance.html", context)
