from django.contrib import messages
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.cache import never_cache
from django.views.decorators.clickjacking import xframe_options_sameorigin

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
        "max_mb": rules.max_upload_bytes(current) // (1024 * 1024),
        "left_today": left_today,
    }
    return render(request, "receipts/new.html", context)


def _receipt_for(request, pk):
    """The receipt, if the user may see it: the resident who sent it, or an
    admin of their dormitory. Anyone else (managers included) gets 404, which
    says nothing about whether the receipt exists."""
    if not request.user.is_authenticated:
        raise Http404
    receipt = get_object_or_404(Receipt.objects.select_related("resident"), pk=pk)
    user = request.user
    is_owner = getattr(user, "resident", None) == receipt.resident
    is_admin = roles.has_role(user, roles.ADMIN) and get_user_dormitory(user) == (
        receipt.resident.dormitory
    )
    if not (is_owner or is_admin):
        raise Http404
    return receipt, is_admin


def _stored(receipt):
    """Whether the file is still on disk (it may have been deleted for
    retention, or lost, e.g. when the demo's disk is wiped)."""
    return bool(receipt.file) and receipt.file.storage.exists(receipt.file.name)


def _file_response(receipt, *, inline):
    extension = receipt.file.name.rsplit(".", 1)[-1]
    response = FileResponse(
        receipt.file.open("rb"),
        as_attachment=not inline,
        filename=f"receipt-{receipt.pk}.{extension}",
        content_type=receipt.content_type,
    )
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, no-store"
    return response


# The file shown inside our viewer page: sandboxed (no scripts, no forms, its
# own opaque origin), nothing loaded from anywhere, and only our own pages may
# embed it. Uploaded files are untrusted, even after the checks at upload.
INLINE_CSP = (
    "sandbox; default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; frame-ancestors 'self'"
)


@never_cache
def file(request, pk):
    """Download the receipt file (always as an attachment)."""
    receipt, _is_admin = _receipt_for(request, pk)
    if not _stored(receipt):
        raise Http404
    return _file_response(receipt, inline=False)


@never_cache
@xframe_options_sameorigin
def inline(request, pk):
    """The receipt file for the viewer page, shown in place, sandboxed."""
    receipt, _is_admin = _receipt_for(request, pk)
    if not _stored(receipt):
        raise Http404
    response = _file_response(receipt, inline=True)
    response["Content-Security-Policy"] = INLINE_CSP
    return response


@never_cache
def view(request, pk):
    """A page that shows the receipt (picture or PDF) with a download button,
    for the resident who sent it and for admins: on a phone a silent
    download looks like nothing happened."""
    receipt, is_admin = _receipt_for(request, pk)
    context = {
        "receipt": receipt,
        "stored": _stored(receipt),
        "is_image": receipt.content_type.startswith("image/"),
        "back": "admin" if is_admin else "resident",
    }
    return render(request, "receipts/view.html", context)
