"""Managing residents: the only code that adds, edits, turns off, erases or
deletes residents. Every function writes an audit event in the same
transaction as the change.

Rules (docs/plans/admin-and-payments.md, stage 1b):
- A resident with any history (bookings or money) is never deleted: their
  access is turned off, or their personal data is erased.
- Turning off or erasing a resident who owes money needs an explicit
  confirmation; the amount owed goes into the audit event.
"""

import uuid

from django.contrib.auth.models import Group
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.audit.models import AuditEvent
from apps.audit.services import record, snapshot

from . import roles
from .models import Resident, User

# Fields that identify a person. Erasing a resident blanks them everywhere,
# including old audit snapshots.
PERSONAL_FIELDS = (
    "full_name",
    "room",
    "student_code",
    "username",
    "first_name",
    "last_name",
    "email",
)


class ResidentError(Exception):
    message = _("This action is not possible.")

    def __init__(self, message=None):
        if message is not None:
            self.message = message
        super().__init__(str(self.message))


class DebtNotConfirmed(ResidentError):
    message = _("This resident owes money. Confirm that you have seen the debt.")


class HasHistory(ResidentError):
    message = _("This resident has bookings or payments and cannot be deleted.")


class AlreadyErased(ResidentError):
    message = _("This resident's personal data has already been erased.")


def _balance(resident):
    from apps.ledger.models import LedgerEntry

    return LedgerEntry.objects.balance(resident)


def has_history(resident):
    """True if anything refers to this resident: bookings (and so key
    hand-overs) or money movements. Receipts (stage 4) will be added here."""
    return resident.bookings.exists() or resident.ledger_entries.exists()


def create_resident(*, actor, dormitory, full_name, room, student_code, language="ru"):
    """A new resident without a PIN; they choose it through a login link."""
    with transaction.atomic():
        # The username is internal and random, so it never contains the student code.
        user = User(username=f"r-{uuid.uuid4().hex[:12]}")
        user.set_unusable_password()
        user.save()
        user.groups.add(Group.objects.get(name=roles.RESIDENT))
        resident = Resident.objects.create(
            user=user,
            dormitory=dormitory,
            full_name=full_name.strip(),
            room=room.strip(),
            student_code=student_code.strip(),
            language=language,
        )
        record(actor=actor, action="resident.create", target=resident, after=snapshot(resident))
    return resident


def update_resident(*, actor, resident, **fields):
    """Change name, room, student code or language."""
    allowed = {"full_name", "room", "student_code", "language"}
    if set(fields) - allowed:
        raise ValueError(f"Unknown fields: {set(fields) - allowed}")
    if resident.is_anonymized:
        raise AlreadyErased
    with transaction.atomic():
        before = snapshot(resident)
        for name, value in fields.items():
            setattr(resident, name, value.strip() if isinstance(value, str) else value)
        resident.save()
        after = snapshot(resident)
        if before != after:
            record(
                actor=actor, action="resident.update", target=resident, before=before, after=after
            )
    return resident


def _check_debt(resident, confirm_debt):
    balance = _balance(resident)
    if balance < 0 and not confirm_debt:
        raise DebtNotConfirmed
    return balance


def deactivate(*, actor, resident, confirm_debt=False, reason=""):
    """Turn off access: the resident can no longer log in. Reversible."""
    with transaction.atomic():
        balance = _check_debt(resident, confirm_debt)
        resident.user.is_active = False
        resident.user.save(update_fields=["is_active"])
        record(
            actor=actor,
            action="resident.deactivate",
            target=resident,
            after={"balance": balance, "debt_confirmed": balance < 0},
            reason=reason,
        )


def reactivate(*, actor, resident):
    if resident.is_anonymized:
        raise AlreadyErased
    with transaction.atomic():
        resident.user.is_active = True
        resident.user.save(update_fields=["is_active"])
        record(actor=actor, action="resident.reactivate", target=resident)


def anonymize(*, actor, resident, confirm_debt=False):
    """Erase name, room and student code (here and in old audit snapshots),
    turn off access and make the PIN unusable. Bookings and money stay, so the
    payment history still adds up. Not reversible."""
    if resident.is_anonymized:
        raise AlreadyErased
    with transaction.atomic():
        balance = _check_debt(resident, confirm_debt)
        resident.full_name = ""
        resident.room = ""
        # Unique per dormitory, so a random placeholder; never shown in the UI.
        resident.student_code = f"erased-{uuid.uuid4().hex[:12]}"
        resident.anonymized_at = timezone.now()
        resident.save()
        user = resident.user
        user.username = f"erased-{uuid.uuid4().hex[:12]}"
        user.first_name = user.last_name = user.email = ""
        user.is_active = False
        user.set_unusable_password()
        user.save()
        _redact_audit(resident)
        record(
            actor=actor,
            action="resident.anonymize",
            target=resident,
            after={"balance": balance, "debt_confirmed": balance < 0},
        )


def _redact_audit(resident):
    """Blank personal fields in old audit events about this resident or their
    login, keeping ids and amounts. The one permitted change to audit events."""
    events = AuditEvent.objects.filter(
        Q(target_type="accounts.Resident", target_id=str(resident.pk))
        | Q(target_type="accounts.User", target_id=str(resident.user_id))
    )
    for event in events:
        redacted = {}
        for side in ("before", "after"):
            data = getattr(event, side)
            if isinstance(data, dict):
                data = {k: ("" if k in PERSONAL_FIELDS else v) for k, v in data.items()}
            redacted[side] = data
        # queryset.update() bypasses AuditEvent.save(), which refuses edits on purpose.
        AuditEvent.objects.filter(pk=event.pk).update(target_repr="", **redacted)


def delete_resident(*, actor, resident):
    """Only for residents with no history (e.g. added by mistake)."""
    if has_history(resident):
        raise HasHistory
    with transaction.atomic():
        record(actor=actor, action="resident.delete", target=resident, before=snapshot(resident))
        user = resident.user
        resident.delete()
        user.delete()
