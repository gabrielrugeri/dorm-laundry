"""Sending a receipt: checks, then the balance is topped up at once.

Trust by default (docs/plans/admin-and-payments.md, Stage 4): a receipt that
passes every check credits the declared amount immediately; the admin reviews
and can void it later. Guardrails come from the money and upload rules
(apps/dorms/rules.py): largest amount per receipt, the most money one
resident may receive from receipts in 30 days, receipts per day, and file
size. The same file can never be sent twice, by anyone.

Everything that is saved happens in one transaction with the resident's row
locked, so two receipts sent at the same moment cannot both slip under a
limit. A refused receipt is recorded in the history after that transaction
is rolled back, so the record survives.
"""

from datetime import datetime, time, timedelta

from django.core.files.base import ContentFile
from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.accounts.models import Resident
from apps.audit.services import record, snapshot
from apps.dorms import rules
from apps.ledger.models import LedgerEntry

from . import files
from .models import Receipt

MB = 1024 * 1024


class ReceiptRefused(Exception):
    """`message` is translatable and safe to show to the resident."""

    def __init__(self, message, code):
        super().__init__(message)
        self.message, self.code = message, code


def _start_of_local_day(dormitory, now):
    local = timezone.localtime(now, dormitory.tzinfo)
    return datetime.combine(local.date(), time.min, tzinfo=dormitory.tzinfo)


def uploads_today(resident, now=None):
    now = now or timezone.now()
    since = _start_of_local_day(resident.dormitory, now)
    return Receipt.objects.filter(resident=resident, uploaded_at__gte=since).count()


def credited_last_30_days(resident, now=None):
    """Money credited from this resident's receipts in the last 30 days
    (voided receipts do not count)."""
    now = now or timezone.now()
    total = Receipt.objects.filter(
        resident=resident,
        status=Receipt.Status.CREDITED,
        uploaded_at__gt=now - timedelta(days=30),
    ).aggregate(total=Sum("amount"))["total"]
    return total or 0


def _check_limits(resident, amount, current, now):
    if amount < 1:
        raise ReceiptRefused(_("Enter the amount in whole rubles."), "amount")
    if amount > current.max_receipt_amount:
        raise ReceiptRefused(
            _("One receipt can be for at most %(max)s RUB. For more, ask the administration.")
            % {"max": current.max_receipt_amount},
            "max_amount",
        )
    if uploads_today(resident, now) >= current.max_uploads_per_day:
        raise ReceiptRefused(
            _("You have already sent %(count)s receipts today. Try again tomorrow.")
            % {"count": current.max_uploads_per_day},
            "daily_limit",
        )
    if credited_last_30_days(resident, now) + amount > current.max_credit_per_30_days:
        raise ReceiptRefused(
            _(
                "Receipts can top up at most %(max)s RUB in 30 days. "
                "For more, ask the administration."
            )
            % {"max": current.max_credit_per_30_days},
            "30_day_cap",
        )


def _duplicate():
    return ReceiptRefused(
        _("This receipt has already been sent. Each receipt can be used only once."),
        "duplicate",
    )


def submit_receipt(*, resident, amount, upload, now=None):
    """Check the receipt and credit `amount`; returns the Receipt or raises
    ReceiptRefused (recorded in the history either way)."""
    now = now or timezone.now()
    try:
        receipt = _submit(resident, amount, upload, now)
    except ReceiptRefused as refused:
        # Outside the rolled-back transaction, so this record is kept.
        record(
            actor=resident.user,
            action="receipt.refused",
            target=resident,
            after={"amount": amount, "refused_because": str(refused.message)},
            dormitory=resident.dormitory,
        )
        raise
    return receipt


def _submit(resident, amount, upload, now):
    current = rules.current()
    try:
        data, content_type, digest = files.check(upload, current.max_upload_mb * MB)
    except files.FileRefused as refused:
        raise ReceiptRefused(refused.message, refused.code) from None
    stored_name = None
    try:
        with transaction.atomic():
            Resident.objects.select_for_update().get(pk=resident.pk)
            if Receipt.objects.filter(sha256=digest).exists():
                raise _duplicate()
            _check_limits(resident, amount, current, now)
            receipt = Receipt(
                resident=resident,
                amount=amount,
                sha256=digest,
                content_type=content_type,
                size=len(data),
                uploaded_at=now,
            )
            receipt.file.save("receipt", ContentFile(data), save=False)
            stored_name = receipt.file.name
            receipt.save()
            LedgerEntry.objects.create(
                resident=resident,
                kind=LedgerEntry.Kind.CREDIT,
                amount=amount,
                receipt=receipt,
            )
            record(
                actor=resident.user,
                action="receipt.credit",
                target=receipt,
                after=snapshot(receipt, exclude=["file", "sha256"]),
                dormitory=resident.dormitory,
            )
    except IntegrityError:
        # Someone sent the same file at the same moment: the unique fingerprint won.
        _remove(stored_name)
        if Receipt.objects.filter(sha256=digest).exists():
            raise _duplicate() from None
        raise
    except BaseException:
        _remove(stored_name)
        raise
    return receipt


def _remove(name):
    """Delete a file saved by a transaction that did not commit."""
    if name:
        Receipt._meta.get_field("file").storage.delete(name)
