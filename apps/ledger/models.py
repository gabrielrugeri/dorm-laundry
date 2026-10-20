from django.conf import settings
from django.db import models
from django.db.models import Q, Sum
from django.utils.translation import gettext_lazy as _

from apps.accounts.models import Resident
from apps.bookings.models import Booking


class LedgerEntryQuerySet(models.QuerySet):
    def balance(self, resident):
        """Current balance in whole rubles: the sum of all the resident's entries."""
        return self.filter(resident=resident).aggregate(total=Sum("amount"))["total"] or 0

    def debt_since(self, resident):
        """When the resident's current debt began: the time of the entry that
        took the balance below zero for the last time. None if not in debt."""
        balance, since = 0, None
        for amount, created_at in (
            self.filter(resident=resident)
            .order_by("created_at", "id")
            .values_list("amount", "created_at")
        ):
            was_negative = balance < 0
            balance += amount
            if balance < 0 and not was_negative:
                since = created_at
            elif balance >= 0:
                since = None
        return since


class LedgerEntry(models.Model):
    """One money movement on a resident's account, in whole rubles.

    The ledger is append-only: entries are never edited or deleted. Mistakes
    are fixed with a new `adjustment` entry. The balance is always the sum of
    entries; it is never stored.

    Sign of `amount` by kind (enforced by the database):
      credit      > 0  money received by the admin (cash, transfer)
      booking     < 0  price charged for a booking
      refund      > 0  booking price returned on a valid cancellation
      adjustment != 0  manual correction, with a note
    """

    class Kind(models.TextChoices):
        # Labels are the plain words from docs/GLOSSARY.md.
        CREDIT = "credit", _("payment received")
        BOOKING = "booking", _("booking payment")
        REFUND = "refund", _("refund")
        ADJUSTMENT = "adjustment", _("balance correction")

    resident = models.ForeignKey(
        Resident,
        on_delete=models.PROTECT,
        related_name="ledger_entries",
        verbose_name=_("resident"),
    )
    amount = models.IntegerField(_("amount (RUB)"))
    kind = models.CharField(_("kind"), max_length=16, choices=Kind.choices)
    booking = models.ForeignKey(
        Booking,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="ledger_entries",
        verbose_name=_("booking"),
    )
    note = models.TextField(_("note"), blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("created by"),
        help_text=_("Who recorded this entry (empty for automatic entries)."),
    )
    created_at = models.DateTimeField(_("created at"), auto_now_add=True)

    objects = LedgerEntryQuerySet.as_manager()

    class Meta:
        verbose_name = _("ledger entry")
        verbose_name_plural = _("ledger entries")
        ordering = ["-created_at", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(kind__in=["credit", "refund"], amount__gt=0)
                    | Q(kind="booking", amount__lt=0)
                    | (Q(kind="adjustment") & ~Q(amount=0))
                ),
                name="ledger_amount_sign_matches_kind",
            ),
            models.CheckConstraint(
                condition=(
                    Q(kind__in=["booking", "refund"], booking__isnull=False)
                    | Q(kind__in=["credit", "adjustment"], booking__isnull=True)
                ),
                name="ledger_booking_only_for_booking_and_refund",
            ),
            # A booking is charged at most once and refunded at most once.
            models.UniqueConstraint(
                fields=["booking", "kind"],
                condition=Q(kind__in=["booking", "refund"]),
                name="unique_charge_and_refund_per_booking",
            ),
        ]
        indexes = [models.Index(fields=["resident", "created_at"])]

    def __str__(self):
        return f"{self.get_kind_display()} {self.amount:+d}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValueError("Ledger entries are append-only; add an adjustment instead.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("Ledger entries are append-only and cannot be deleted.")
