import uuid

from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.accounts.models import Resident
from apps.core.storage import private_storage


def receipt_path(instance, filename):
    """A random name: never the uploaded file name, which may hold personal data."""
    extension = {
        "application/pdf": ".pdf",
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
    }.get(instance.content_type, "")
    now = timezone.now()
    return f"receipts/{now:%Y/%m}/{uuid.uuid4().hex}{extension}"


class Receipt(models.Model):
    """A payment receipt a resident sent. Trusted by default: sending it
    credits the amount at once (one ledger entry linked to it). The admin can
    void it later (Stage 5).

    Refers to the resident by id only. The SHA-256 of the original file is
    kept even if the file is later deleted for retention, so the same receipt
    can never be sent twice, by anyone.
    """

    class Status(models.TextChoices):
        CREDITED = "credited", _("credited")
        VOIDED = "voided", _("voided")

    resident = models.ForeignKey(
        Resident, on_delete=models.PROTECT, related_name="receipts", verbose_name=_("resident")
    )
    amount = models.PositiveIntegerField(_("amount (RUB)"))
    sha256 = models.CharField(_("file fingerprint"), max_length=64, unique=True)
    file = models.FileField(
        _("file"), storage=private_storage, upload_to=receipt_path, blank=True, max_length=200
    )
    content_type = models.CharField(_("file type"), max_length=32)
    size = models.PositiveIntegerField(_("file size (bytes)"))
    status = models.CharField(
        _("status"), max_length=16, choices=Status.choices, default=Status.CREDITED
    )
    uploaded_at = models.DateTimeField(_("sent at"), default=timezone.now)
    voided_at = models.DateTimeField(_("voided at"), null=True, blank=True)
    voided_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("voided by"),
    )
    void_reason = models.TextField(_("why it was voided"), blank=True)

    class Meta:
        verbose_name = _("receipt")
        verbose_name_plural = _("receipts")
        ordering = ["-uploaded_at", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0), name="receipt_amount_positive"
            ),
            # A voided receipt always says when and why.
            models.CheckConstraint(
                condition=models.Q(status="credited", voided_at__isnull=True)
                | (models.Q(status="voided", voided_at__isnull=False) & ~models.Q(void_reason="")),
                name="receipt_void_has_time_and_reason",
            ),
        ]
        indexes = [models.Index(fields=["resident", "uploaded_at"])]

    def __str__(self):
        return str(_("Receipt no. %(number)s") % {"number": self.pk})
