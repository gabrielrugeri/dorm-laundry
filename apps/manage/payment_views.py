"""Payment details in the admin area (/manage/settings/payments/): how
residents pay. A sensitive setting, like the money rules: the admin's
password and a reason, and every change in the history."""

from django.contrib import messages
from django.shortcuts import redirect, render
from django.utils.translation import gettext as _

from apps.payments import services
from apps.payments.models import PaymentDetails

from .forms import PaymentDetailsForm
from .views import admin_required


@admin_required
def payment_details_edit(request):
    details = PaymentDetails.objects.filter(dormitory=request.dormitory).first()
    form = PaymentDetailsForm(
        request.POST or None, request.FILES or None, user=request.user, details=details
    )
    if request.method == "POST" and form.is_valid():
        services.change_details(
            actor=request.user,
            dormitory=request.dormitory,
            values={name: form.cleaned_data[name] for name in services.FIELDS},
            reason=form.cleaned_data["reason"],
            qr_png=form.cleaned_data.get("qr_image"),
            remove_qr=form.cleaned_data.get("remove_qr", False),
        )
        messages.success(request, _("Payment details saved. Residents see them now."))
        return redirect("manage:settings")
    return render(request, "manage/payment_details.html", {"form": form, "details": details})
