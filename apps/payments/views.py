from django.http import FileResponse, Http404
from django.shortcuts import render

from apps.accounts.decorators import get_user_dormitory, resident_required

from .models import PaymentDetails


@resident_required
def how_to_pay(request):
    """Where to send money, with copy buttons and the resident's own payment
    purpose (their room and code, shown only to them)."""
    resident = request.user.resident
    details = PaymentDetails.objects.filter(dormitory=request.dormitory).first()
    context = {
        "details": details,
        "purpose": details.purpose_for(resident) if details else "",
    }
    return render(request, "payments/how_to_pay.html", context)


def qr_image(request):
    """The dormitory's SBP QR code, for people of that dormitory only."""
    dormitory = get_user_dormitory(request.user) if request.user.is_authenticated else None
    details = PaymentDetails.objects.filter(dormitory=dormitory).first() if dormitory else None
    if details is None or not details.qr_image:
        raise Http404
    if not details.qr_image.storage.exists(details.qr_image.name):
        raise Http404
    response = FileResponse(details.qr_image.open("rb"), content_type="image/png")
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, max-age=300"
    return response
