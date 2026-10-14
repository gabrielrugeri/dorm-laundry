import uuid

from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _
from django.utils.translation import pgettext_lazy

from apps.accounts.models import Resident
from apps.dorms.models import Machine, TimeSlot


class Booking(models.Model):
    """One machine for one slot on one day.

    Booking several consecutive slots creates one Booking per slot, all sharing
    the same `group_id`, so they are shown and confirmed together.

    Double-booking is prevented by the database: at most one non-cancelled
    booking may exist per (machine, date, slot). Completed bookings still
    occupy their slot.

    Create and cancel bookings through the booking service (not by hand), so
    the ledger and the dormitory checks stay consistent.
    """

    class Status(models.TextChoices):
        ACTIVE = "active", pgettext_lazy("booking status", "active")
        CANCELLED = "cancelled", pgettext_lazy("booking status", "cancelled")
        COMPLETED = "completed", pgettext_lazy("booking status", "completed")

    machine = models.ForeignKey(
        Machine, on_delete=models.PROTECT, related_name="bookings", verbose_name=_("machine")
    )
    date = models.DateField(_("date"), help_text=_("Local date in the dormitory's timezone."))
    slot = models.ForeignKey(
        TimeSlot, on_delete=models.PROTECT, related_name="bookings", verbose_name=_("time slot")
    )
    resident = models.ForeignKey(
        Resident, on_delete=models.PROTECT, related_name="bookings", verbose_name=_("resident")
    )
    status = models.CharField(
        _("status"), max_length=16, choices=Status.choices, default=Status.ACTIVE
    )
    group_id = models.UUIDField(
        _("group"),
        default=uuid.uuid4,
        db_index=True,
        help_text=_("Shared by consecutive slots booked together."),
    )
    price_rub = models.PositiveIntegerField(
        _("price (RUB)"), help_text=_("Price charged when booked; refunds use this amount.")
    )
    # Derived from date + slot on save; stored in UTC to make time queries simple.
    starts_at = models.DateTimeField(_("starts at"), editable=False)
    ends_at = models.DateTimeField(_("ends at"), editable=False)
    created_at = models.DateTimeField(_("created at"), auto_now_add=True)
    cancelled_at = models.DateTimeField(_("cancelled at"), null=True, blank=True)

    class Meta:
        verbose_name = _("booking")
        verbose_name_plural = _("bookings")
        ordering = ["starts_at", "machine"]
        constraints = [
            models.UniqueConstraint(
                fields=["machine", "date", "slot"],
                condition=~models.Q(status="cancelled"),
                name="unique_occupied_machine_slot",
            ),
            models.CheckConstraint(
                condition=models.Q(ends_at__gt=models.F("starts_at")),
                name="booking_ends_after_start",
            ),
            models.CheckConstraint(
                condition=~models.Q(status="cancelled") | models.Q(cancelled_at__isnull=False),
                name="cancelled_booking_has_cancelled_at",
            ),
        ]
        indexes = [
            models.Index(fields=["resident", "starts_at"]),
            models.Index(fields=["starts_at"]),
        ]

    def __str__(self):
        return f"{self.machine} {self.date} {self.slot}"

    def save(self, *args, **kwargs):
        self.starts_at, self.ends_at = self.slot.bounds(self.date)
        super().save(*args, **kwargs)

    def clean(self):
        dormitory_ids = {self.machine.dormitory_id, self.slot.dormitory_id}
        if self.resident_id:
            dormitory_ids.add(self.resident.dormitory_id)
        if len(dormitory_ids) > 1:
            raise ValidationError(
                _("Machine, time slot and resident must belong to the same dormitory.")
            )
