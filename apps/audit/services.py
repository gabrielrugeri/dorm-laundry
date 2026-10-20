"""Writing audit events. Call `record()` inside the same transaction as the
change it describes, so the change and its audit event commit or roll back
together.

    with transaction.atomic():
        before = snapshot(resident)
        resident.room = "305"
        resident.save()
        record(actor=request.user, action="resident.change", target=resident,
               before=before, after=snapshot(resident))
"""

import json

from django.core.serializers.json import DjangoJSONEncoder
from django.forms.models import model_to_dict

from .models import AuditEvent

# Never stored in snapshots. Only the fact that they changed is recorded.
SECRET_FIELDS = {"password"}


def snapshot(instance, exclude=()):
    """A JSON-safe dict of the instance's field values, without secrets."""
    if instance is None:
        return None
    data = model_to_dict(instance, exclude=[*SECRET_FIELDS, *exclude])
    # Related objects become their ids; dates and UUIDs become strings.
    return json.loads(json.dumps(data, cls=DjangoJSONEncoder, default=str))


def _dormitory_of(target):
    """Best guess at the dormitory an object belongs to, for filtering."""
    paths = (
        "dormitory",
        "resident.dormitory",
        "staff_profile.dormitory",
        "machine.dormitory",
        "booking.machine.dormitory",
    )
    for path in paths:
        obj = target
        for name in path.split("."):
            obj = getattr(obj, name, None)
            if obj is None:
                break
        if obj is not None:
            return obj
    return None


def record(*, actor, action, target=None, before=None, after=None, reason="", dormitory=None):
    """Write one audit event and return it."""
    if dormitory is None and target is not None:
        dormitory = _dormitory_of(target)
    return AuditEvent.objects.create(
        actor=actor if actor is not None and actor.is_authenticated else None,
        dormitory=dormitory,
        action=action,
        target_type=target._meta.label if target is not None else "",
        target_id=str(target.pk) if target is not None else "",
        target_repr=str(target)[:200] if target is not None else "",
        before=before,
        after=after,
        reason=reason,
    )
