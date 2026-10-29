"""Changing a dormitory's payment details: a sensitive setting. The screen
asks for the admin's password and a reason (apps/manage/payment_views.py);
this records the change with old and new values."""

import io

from django.core.files.base import ContentFile
from django.db import transaction
from django.utils.translation import gettext_lazy as _
from PIL import Image, UnidentifiedImageError

from apps.audit.services import record, snapshot

from .models import PaymentDetails

FIELDS = (
    "recipient",
    "bank",
    "sbp_phone",
    "payment_link",
    "bik",
    "account",
    "inn",
    "purpose_prefix",
)

# Plain words for the change history (docs/GLOSSARY.md).
LABELS = {
    "recipient": _("Recipient"),
    "bank": _("Bank"),
    "sbp_phone": _("Phone number for SBP"),
    "payment_link": _("Payment link from the bank"),
    "bik": _("BIK"),
    "account": _("Account number"),
    "inn": _("Recipient's INN"),
    "purpose_prefix": _("Start of the payment purpose"),
    "qr_changed": _("SBP QR code changed"),
}

MAX_QR_BYTES = 2 * 1024 * 1024


class QrRefused(ValueError):
    pass


def clean_qr(uploaded):
    """The QR picture saved again as PNG (metadata dropped), or QrRefused."""
    if uploaded.size > MAX_QR_BYTES:
        raise QrRefused(_("The picture is too large (2 MB at most)."))
    try:
        with Image.open(uploaded) as image:
            if image.format not in ("PNG", "JPEG", "WEBP"):
                raise QrRefused(_("Send the QR code as a PNG or JPEG picture."))
            image.load()
            out = io.BytesIO()
            image.convert("RGB").save(out, "PNG")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise QrRefused(_("This picture cannot be read.")) from None
    return out.getvalue()


def change_details(*, actor, dormitory, values, reason, qr_png=None, remove_qr=False):
    reason = reason.strip()
    if not reason:
        raise ValueError("A reason is required.")
    with transaction.atomic():
        details = PaymentDetails.objects.select_for_update().filter(dormitory=dormitory).first()
        before = snapshot(details, exclude=["qr_image"]) if details else None
        if details is None:
            details = PaymentDetails(dormitory=dormitory)
        for name in FIELDS:
            setattr(details, name, values[name])
        qr_changed = False
        if qr_png is not None:
            if details.qr_image:
                details.qr_image.delete(save=False)
            details.qr_image.save("qr.png", ContentFile(qr_png), save=False)
            qr_changed = True
        elif remove_qr and details.qr_image:
            details.qr_image.delete(save=False)
            qr_changed = True
        details.save()
        after = snapshot(details, exclude=["qr_image"])
        if qr_changed:
            after["qr_changed"] = True
        record(
            actor=actor,
            action="payments.details_change",
            target=details,
            before=before,
            after=after,
            reason=reason,
            dormitory=dormitory,
        )
    return details
