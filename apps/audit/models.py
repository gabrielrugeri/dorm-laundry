from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.dorms.models import Dormitory


class AuditEvent(models.Model):
    """One admin action: who did what to which object, and when.

    Append-only: events are never edited or deleted by the application. The
    only exception is privacy redaction when a resident is anonymized (stage
    1b), which blanks personal fields in `before`/`after` and is itself audited.

    `before` and `after` are JSON snapshots of the changed object. Passwords and
    PINs are never stored, only the fact that they changed.

    Staff-only: snapshots can contain residents' names and rooms.
    """

    created_at = models.DateTimeField(_("when"), auto_now_add=True, db_index=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("who"),
        help_text=_("Empty for actions done by the system."),
    )
    dormitory = models.ForeignKey(
        Dormitory,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("dormitory"),
    )
    action = models.CharField(_("action"), max_length=64, db_index=True)
    target_type = models.CharField(_("object type"), max_length=64, blank=True)
    target_id = models.CharField(_("object id"), max_length=64, blank=True)
    target_repr = models.CharField(_("object"), max_length=200, blank=True)
    before = models.JSONField(_("before"), null=True, blank=True, encoder=DjangoJSONEncoder)
    after = models.JSONField(_("after"), null=True, blank=True, encoder=DjangoJSONEncoder)
    reason = models.TextField(_("reason"), blank=True)

    class Meta:
        verbose_name = _("audit event")
        verbose_name_plural = _("audit log")
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["target_type", "target_id"])]

    def __str__(self):
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.action} {self.target_repr}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValueError("Audit events are append-only.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("Audit events cannot be deleted.")

    @property
    def changes(self):
        """[(field, old, new), ...] for fields that differ between snapshots."""
        before, after = self.before or {}, self.after or {}
        fields = sorted(set(before) | set(after))
        return [(f, before.get(f), after.get(f)) for f in fields if before.get(f) != after.get(f)]
