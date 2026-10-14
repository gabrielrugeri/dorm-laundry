from django.conf import settings
from django.db import models
from django.db.models import F, Max, Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.bookings.models import Booking


class KeyLog(models.Model):
    """When the key for a booking was taken and returned, recorded by the manager.

    Consecutive slots booked together (same `group_id`) need the key only once,
    so the log belongs to the first booking of the group. The key is due back
    at the end of the group's last slot.
    """

    booking = models.OneToOneField(
        Booking, on_delete=models.PROTECT, related_name="key_log", verbose_name=_("booking")
    )
    taken_at = models.DateTimeField(_("key taken at"), null=True, blank=True)
    returned_at = models.DateTimeField(_("key returned at"), null=True, blank=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("recorded by"),
    )
    note = models.TextField(_("note"), blank=True)

    class Meta:
        verbose_name = _("key log entry")
        verbose_name_plural = _("key log")
        ordering = ["-booking__starts_at"]
        constraints = [
            models.CheckConstraint(
                condition=Q(returned_at__isnull=True)
                | Q(taken_at__isnull=False, returned_at__gte=F("taken_at")),
                name="key_returned_after_taken",
            ),
        ]

    def __str__(self):
        return str(self.booking)

    @property
    def due_at(self):
        """End of the last non-cancelled slot in the booking's group."""
        group = Booking.objects.filter(group_id=self.booking.group_id).exclude(
            status=Booking.Status.CANCELLED
        )
        return group.aggregate(end=Max("ends_at"))["end"] or self.booking.ends_at

    def is_overdue(self, now=None):
        now = now or timezone.now()
        return self.taken_at is not None and self.returned_at is None and now > self.due_at
