from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.dorms.models import Dormitory


class User(AbstractUser):
    """Login account for residents, managers and admins.

    Kept as our own model from the first migration so we can add fields later
    without a painful migration. Profile data lives in `Resident` / `StaffProfile`.
    Roles are Django groups; see `apps.accounts.roles`.
    """


class Resident(models.Model):
    """A person living in a dormitory who can book machines.

    Privacy: `full_name` and `room` are visible only to managers and admins.
    Never show them (or `str(resident)`) on resident-facing pages.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="resident",
        verbose_name=_("user"),
    )
    dormitory = models.ForeignKey(
        Dormitory, on_delete=models.PROTECT, related_name="residents", verbose_name=_("dormitory")
    )
    student_code = models.CharField(_("student code"), max_length=32)
    full_name = models.CharField(_("full name"), max_length=200)
    room = models.CharField(_("room"), max_length=20)
    language = models.CharField(
        _("language"), max_length=8, choices=settings.LANGUAGES, default="ru"
    )
    anonymized_at = models.DateTimeField(
        _("personal data erased at"),
        null=True,
        blank=True,
        help_text=_("Set when the resident's name, room and code were erased."),
    )

    class Meta:
        verbose_name = _("resident")
        verbose_name_plural = _("residents")
        ordering = ["dormitory", "room", "full_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["dormitory", "student_code"], name="unique_student_code_per_dormitory"
            ),
        ]

    def __str__(self):
        if self.is_anonymized:
            return str(_("Former resident"))
        return f"{self.full_name} ({self.room})"

    @property
    def is_anonymized(self):
        return self.anonymized_at is not None


class StaffProfile(models.Model):
    """Links a manager or admin account to the dormitory they work for.

    Staff only see and change data of their own dormitory.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="staff_profile",
        verbose_name=_("user"),
    )
    dormitory = models.ForeignKey(
        Dormitory,
        on_delete=models.PROTECT,
        related_name="staff_profiles",
        verbose_name=_("dormitory"),
    )

    class Meta:
        verbose_name = _("staff profile")
        verbose_name_plural = _("staff profiles")

    def __str__(self):
        return f"{self.user} @ {self.dormitory}"
