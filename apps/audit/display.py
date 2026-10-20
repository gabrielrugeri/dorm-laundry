"""Show audit snapshots in plain words (docs/CLAUDE.md, Admin UI principles).

The audit log stores raw field values; admins must never see field names,
ids, codes, JSON or UTC times. `describe_changes(event)` turns an event's
before/after snapshots into [(label, old, new), ...] in the admin's language:
field labels from the models, choice codes as their names, times in Moscow
time, money as "50 ₽", yes/no for flags. Internal fields are left out.
"""

from django.apps import apps
from django.core.exceptions import FieldDoesNotExist
from django.db import models
from django.utils import formats, timezone
from django.utils.dateparse import parse_date, parse_datetime
from django.utils.translation import gettext as _

from apps.core.templatetags.money import rub

# Never shown: ids, links between records, internal flags and timestamps.
HIDDEN = {
    "id",
    "user",
    "dormitory",
    "resident",
    "machine",
    "slot",
    "booking",
    "group_id",
    "created_by",
    "recorded_by",
    "password",
    "username",
    "last_login",
    "is_superuser",
    "is_staff",
    "user_permissions",
    "date_joined",
    "starts_at",
    "ends_at",
    "created_at",
}

MONEY = {"amount", "price_rub", "refund_rub", "balance", "price_per_slot"}


def _extra_labels():
    """Values services add to snapshots that are not model fields."""
    return {
        "refund_rub": _("Refunded"),
        "full_refund": _("Full refund"),
        "balance": _("Balance"),
        "debt_confirmed": _("Debt seen and confirmed"),
        "groups": _("Role"),
    }


def _role_name(name):
    return {
        "resident": _("Resident"),
        "manager": _("Key manager"),
        "admin": _("Administrator"),
    }.get(name, name)


def _model(event):
    try:
        return apps.get_model(event.target_type) if event.target_type else None
    except (LookupError, ValueError):
        return None


def _field(model, name):
    try:
        return model._meta.get_field(name) if model else None
    except FieldDoesNotExist:
        return None


def _format(name, field, value):
    if value in (None, "", []):
        return "—"
    if name == "groups":
        return ", ".join(str(_role_name(v)) for v in value)
    if isinstance(value, bool):
        return _("Yes") if value else _("No")
    if name in MONEY and isinstance(value, int):
        return rub(value)
    if field is not None and field.choices:
        return str(dict(field.flatchoices).get(value, value))
    if isinstance(field, models.DateTimeField) and isinstance(value, str):
        moment = parse_datetime(value)
        if moment is not None:
            return formats.date_format(timezone.localtime(moment), "j E Y, H:i")
    if isinstance(field, models.DateField) and isinstance(value, str):
        day = parse_date(value)
        if day is not None:
            return formats.date_format(day, "j E Y")
    return str(value)


def describe_changes(event):
    """[(label, old, new), ...] for the fields an admin can understand."""
    model = _model(event)
    extra = _extra_labels()
    rows = []
    for name, old, new in event.changes:
        if name in HIDDEN:
            continue
        field = _field(model, name)
        if name in extra:
            label = str(extra[name])  # our plain words win over model field names
        elif field is not None:
            label = str(field.verbose_name).capitalize()
        else:
            continue  # unknown internal value: leave it out
        rows.append((label, _format(name, field, old), _format(name, field, new)))
    return rows
