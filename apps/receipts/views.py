from django.contrib import messages
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.cache import never_cache

from apps.accounts import roles
from apps.accounts.decorators import get_user_dormitory, resident_required
from apps.core.templatetags.money import rub
from apps.dorms import rules
from apps.ledger.models import LedgerEntry

from . import services
from .forms import ReceiptForm
from .models import Receipt


@resident_required
def new(request):
    """Send a payment receipt: the balance is topped up at once."""
    resident = request.user.resident
    current = rules.current()
    form = ReceiptForm(
        request.POST or None, request.FILES or None, max_amount=current.max_receipt_amount
    )
    if request.method == "POST" and form.is_valid():
        try:
            receipt = services.submit_receipt(
                resident=resident,
                amount=form.cleaned_data["amount"],
                upload=form.cleaned_data["file"],
            )
        except services.ReceiptRefused as refused:
            form.add_error(None, refused.message)
        else:
            messages.success(
                request,
                _("Thank you! Your balance was topped up by %(amount)s.")
                % {"amount": rub(receipt.amount)},
            )
            return redirect("ledger:balance")
    left_today = max(0, current.max_uploads_per_day - services.uploads_today(resident))
    context = {
        "form": form,
        "balance": LedgerEntry.objects.balance(resident),
        "max_amount": current.max_receipt_amount,
        "max_mb": current.max_upload_mb,
        "left_today": left_today,
    }
    return render(request, "receipts/new.html", context)


@never_cache
def file(request, pk):
    """The receipt file, for the resident who sent it or an admin of their
    dormitory. Anyone else (managers included) gets 404, which says nothing
    about whether the receipt exists. Always downloaded, never shown inline."""
    if not request.user.is_authenticated:
        raise Http404
    receipt = get_object_or_404(Receipt.objects.select_related("resident"), pk=pk)
    user = request.user
    is_owner = getattr(user, "resident", None) == receipt.resident
    is_admin = roles.has_role(user, roles.ADMIN) and get_user_dormitory(user) == (
        receipt.resident.dormitory
    )
    if not (is_owner or is_admin) or not receipt.file:
        raise Http404
    if not receipt.file.storage.exists(receipt.file.name):
        # Deleted for retention, or lost (e.g. the demo's disk is wiped on redeploy).
        raise Http404
    extension = receipt.file.name.rsplit(".", 1)[-1]
    response = FileResponse(
        receipt.file.open("rb"),
        as_attachment=True,
        filename=f"receipt-{receipt.pk}.{extension}",
        content_type=receipt.content_type,
    )
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, no-store"
    return response
