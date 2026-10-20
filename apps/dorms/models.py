from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, available_timezones

from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _


def validate_timezone(value):
    if value not in available_timezones():
        raise ValidationError(_("Unknown timezone: %(value)s"), params={"value": value})


class Dormitory(models.Model):
    """A dormitory with its own machines, residents, slots and prices.

    Everything else belongs to a dormitory, and every query is scoped by it.
    """

    name = models.CharField(_("name"), max_length=200)
    slug = models.SlugField(_("slug"), unique=True)
    timezone = models.CharField(
        _("timezone"), max_length=64, default="Europe/Moscow", validators=[validate_timezone]
    )
    price_per_slot = models.PositiveIntegerField(
        _("price per slot (RUB)"), default=50, help_text=_("Whole rubles per machine per slot.")
    )
    cancellation_cutoff_hours = models.PositiveSmallIntegerField(
        _("cancellation cutoff (hours)"),
        default=2,
        help_text=_("Cancelling at least this many hours before the start gives a refund."),
    )
    booking_horizon_days = models.PositiveSmallIntegerField(
        _("booking horizon (days)"),
        default=7,
        help_text=_("How many days ahead residents can book."),
    )

    class Meta:
        verbose_name = _("dormitory")
        verbose_name_plural = _("dormitories")
        ordering = ["name"]

    def __str__(self):
        return self.name

    @property
    def tzinfo(self):
        return ZoneInfo(self.timezone)


class TimeSlot(models.Model):
    """A bookable period of the day, e.g. 08:00 for 120 minutes.

    Slot hours are data, not code, so each dormitory can configure its own.
    A slot must end on the same day it starts.
    """

    dormitory = models.ForeignKey(
        Dormitory, on_delete=models.PROTECT, related_name="time_slots", verbose_name=_("dormitory")
    )
    start_time = models.TimeField(_("start time"), help_text=_("Local time of the dormitory."))
    duration_minutes = models.PositiveSmallIntegerField(_("duration (minutes)"), default=120)
    active = models.BooleanField(_("active"), default=True)

    class Meta:
        verbose_name = _("time slot")
        verbose_name_plural = _("time slots")
        ordering = ["dormitory", "start_time"]
        constraints = [
            models.UniqueConstraint(
                fields=["dormitory", "start_time"], name="unique_slot_start_per_dormitory"
            ),
            models.CheckConstraint(
                condition=models.Q(duration_minutes__gt=0), name="slot_duration_positive"
            ),
        ]

    def __str__(self):
        return f"{self.start_time:%H:%M}–{self.end_time:%H:%M}"

    @property
    def end_time(self):
        start = datetime.combine(datetime.min, self.start_time)
        return (start + timedelta(minutes=self.duration_minutes)).time()

    def clean(self):
        minutes_from_midnight = self.start_time.hour * 60 + self.start_time.minute
        if minutes_from_midnight + self.duration_minutes > 24 * 60:
            raise ValidationError(_("A slot must end on the same day it starts."))

    def bounds(self, day):
        """Return (start, end) of this slot on `day` as aware datetimes.

        `day` is a local calendar date in the dormitory's timezone.
        """
        start = datetime.combine(day, self.start_time, tzinfo=self.dormitory.tzinfo)
        return start, start + timedelta(minutes=self.duration_minutes)


class Machine(models.Model):
    """A washing machine. Residents see it as "Machine 3" in their language."""

    dormitory = models.ForeignKey(
        Dormitory, on_delete=models.PROTECT, related_name="machines", verbose_name=_("dormitory")
    )
    number = models.PositiveSmallIntegerField(
        _("number"), help_text=_("Shown as “Machine 3” in the selected language.")
    )
    active = models.BooleanField(
        _("active"), default=True, help_text=_("Inactive machines cannot be booked.")
    )

    class Meta:
        verbose_name = _("machine")
        verbose_name_plural = _("machines")
        ordering = ["dormitory", "number"]
        constraints = [
            models.UniqueConstraint(
                fields=["dormitory", "number"], name="unique_machine_number_per_dormitory"
            ),
        ]

    def __str__(self):
        return self.name

    @property
    def name(self):
        """ "Machine 3" / "Машина 3", in the language of the current request."""
        return gettext("Machine %(number)s") % {"number": self.number}
