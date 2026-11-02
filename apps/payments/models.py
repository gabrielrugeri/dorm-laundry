from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.storage import private_storage
from apps.dorms.models import Dormitory

from .validators import format_phone


def qr_path(instance, filename):
    return f"payment-qr/{instance.dormitory_id}.png"


class PaymentDetails(models.Model):
    """How residents of one dormitory pay: shown on the "How to pay" page.

    Filled in by the dormitory's admin from what the administration's bank
    gave them; nothing here is hard-coded. A sensitive setting: changing it
    asks for the password and a reason and is recorded in the history.
    """

    dormitory = models.OneToOneField(
        Dormitory,
        on_delete=models.CASCADE,
        related_name="payment_details",
        verbose_name=_("dormitory"),
    )
    recipient = models.CharField(_("Recipient"), max_length=200)
    bank = models.CharField(_("Bank"), max_length=200)
    sbp_phone = models.CharField(_("Phone number for SBP"), max_length=12, blank=True)
    payment_link = models.URLField(_("Payment link from the bank"), blank=True)
    qr_image = models.FileField(
        _("SBP QR code from the bank"), storage=private_storage, upload_to=qr_path, blank=True
    )
    bik = models.CharField(_("BIK"), max_length=9, blank=True)
    account = models.CharField(_("Account number"), max_length=20, blank=True)
    inn = models.CharField(_("Recipient's INN"), max_length=12, blank=True)
    purpose_prefix = models.CharField(
        _("Start of the payment purpose"),
        max_length=60,
        default="Стирка",
        help_text=_("Residents see e.g. “Стирка, комн. 301-2, код 00111598”."),
    )
    updated_at = models.DateTimeField(_("changed at"), auto_now=True)

    class Meta:
        verbose_name = _("payment details")
        verbose_name_plural = _("payment details")

    def __str__(self):
        return str(self.dormitory)

    @property
    def sbp_phone_display(self):
        return format_phone(self.sbp_phone)

    def purpose_for(self, resident):
        """The payment purpose a resident copies into their bank app. Russian,
        like every payment in Russian banks."""
        return f"{self.purpose_prefix}, комн. {resident.room}, код {resident.student_code}"
