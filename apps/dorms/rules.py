"""Money and upload rules (the GlobalSettings row): reading and changing them.

These numbers decide how far residents may go into debt and how much money
receipts can bring in, so a change is treated as sensitive: values must be
within sensible bounds, a reason is required, the change is recorded in the
history with old and new values, and the admin screen asks for the password
and an extra confirmation for big jumps (see apps/manage/settings_views.py).
Changes apply from now on; nothing that already happened is recalculated.

The largest receipt file is a technical limit, not a money rule: only
superusers change it, in Django admin (apps/dorms/admin.py), through the same
`change_settings`, so it is checked and recorded the same way.
"""

from django.conf import settings
from django.db import transaction
from django.utils.translation import gettext_lazy as _

from apps.audit.services import record, snapshot

from .models import GlobalSettings

# The rules dormitory admins change on /manage/settings/.
FIELDS = (
    "credit_limit",
    "max_receipt_amount",
    "max_credit_per_30_days",
    "max_uploads_per_day",
)
# Superusers only, in Django admin.
SUPERUSER_FIELDS = ("max_upload_mb",)
ALL_FIELDS = FIELDS + SUPERUSER_FIELDS

# Plain words for the admin screens and the history (docs/GLOSSARY.md).
LABELS = {
    "credit_limit": _("May go into debt up to"),
    "max_receipt_amount": _("Largest amount on one receipt"),
    "max_credit_per_30_days": _("Most money for one resident in 30 days"),
    "max_uploads_per_day": _("Receipts one resident may send per day"),
    "max_upload_mb": _("Largest receipt file, MB"),
}
MONEY_FIELDS = {"credit_limit", "max_receipt_amount", "max_credit_per_30_days"}

# A change bigger than this factor (up or down) needs an extra confirmation.
BIG_CHANGE_FACTOR = 10


def bounds():
    """(lowest, highest) allowed for each rule. The file size can never be
    above the server's hard limit for request bodies."""
    hard_mb = max(1, settings.MAX_UPLOAD_BYTES_HARD // (1024 * 1024))
    return {
        "credit_limit": (0, 10_000),  # or empty: no limit
        "max_receipt_amount": (50, 100_000),
        "max_credit_per_30_days": (100, 1_000_000),
        "max_uploads_per_day": (1, 20),
        "max_upload_mb": (1, hard_mb),
    }


def max_upload_bytes(rules=None):
    """The largest receipt file accepted now, never above the server's hard
    limit (which may have been lowered after the rule was saved)."""
    rules = rules or current()
    return min(rules.max_upload_mb * 1024 * 1024, settings.MAX_UPLOAD_BYTES_HARD)


def current():
    """The rules in force (the row is created by a migration; this is a safety net)."""
    rules, _created = GlobalSettings.objects.get_or_create(pk=1)
    return rules


def credit_limit_for(resident):
    """How many rubles `resident` may owe; None means no limit. The same for
    everyone today; a per-dormitory or per-resident override goes here."""
    return current().credit_limit


def is_big_change(old, new):
    """More than 10 times bigger or smaller, from or to zero, or adding or
    removing "no limit"."""
    if old == new:
        return False
    if old is None or new is None or old == 0 or new == 0:
        return True
    return new > old * BIG_CHANGE_FACTOR or new * BIG_CHANGE_FACTOR < old


def big_changes(rules, values):
    return [name for name in FIELDS if is_big_change(getattr(rules, name), values[name])]


class InvalidRules(ValueError):
    pass


def validate(values):
    """Raise InvalidRules unless every value in `values` is within bounds.
    `values` holds all of FIELDS, or any subset of ALL_FIELDS together with
    both receipt amounts."""
    for name, value in values.items():
        low, high = bounds()[name]
        if value is None and name == "credit_limit":
            continue
        if value is None or not low <= value <= high:
            raise InvalidRules(f"{name} must be between {low} and {high}.")
    if values["max_credit_per_30_days"] < values["max_receipt_amount"]:
        raise InvalidRules("The 30-day maximum cannot be below the maximum per receipt.")


def change_settings(*, actor, values, reason):
    """Save new rules and record the change. `values` maps rule names to new
    values: all of FIELDS from /manage/settings/, or only SUPERUSER_FIELDS
    from Django admin. The caller has already checked who may change them
    (and, on /manage/, the password and the extra confirmation)."""
    reason = reason.strip()
    if not reason:
        raise InvalidRules("A reason is required.")
    unknown = set(values) - set(ALL_FIELDS)
    if unknown:
        raise InvalidRules(f"Unknown rules: {sorted(unknown)}")
    with transaction.atomic():
        current()
        rules = GlobalSettings.objects.select_for_update().get(pk=1)
        amounts = {
            name: values.get(name, getattr(rules, name))
            for name in ("max_receipt_amount", "max_credit_per_30_days")
        }
        validate({**values, **amounts})
        before = snapshot(rules)
        for name, value in values.items():
            setattr(rules, name, value)
        rules.save()
        dormitory = getattr(getattr(actor, "staff_profile", None), "dormitory", None)
        record(
            actor=actor,
            action="settings.change",
            target=rules,
            before=before,
            after=snapshot(rules),
            reason=reason,
            dormitory=dormitory,
        )
    return rules
