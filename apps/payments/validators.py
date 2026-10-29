"""Checks for Russian payment details, so a typo is caught before residents
send money to a wrong account. Formats and check digits as published by the
Bank of Russia and the Federal Tax Service."""

import re

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _


def digits(value):
    return re.sub(r"\D", "", value or "")


def normalize_phone(value):
    """ "8 (900) 123-45-67" -> "+79001234567"; ValidationError if not a
    Russian mobile number."""
    number = digits(value)
    if len(number) == 11 and number[0] in "78":
        return "+7" + number[1:]
    if len(number) == 10:
        return "+7" + number
    raise ValidationError(_("Enter a Russian phone number, e.g. +7 900 123-45-67."))


def format_phone(value):
    """ "+79001234567" -> "+7 900 123-45-67"."""
    number = digits(value)
    if len(number) != 11:
        return value
    return f"+7 {number[1:4]} {number[4:7]}-{number[7:9]}-{number[9:11]}"


def validate_bik(value):
    if not re.fullmatch(r"\d{9}", value):
        raise ValidationError(_("The BIK has 9 digits."))


def _weighted(number, weights):
    return sum(int(d) * w for d, w in zip(number, weights, strict=False))


def validate_inn(value):
    """10 digits (organisation) or 12 digits (person), with check digits."""
    if not re.fullmatch(r"\d{10}|\d{12}", value):
        raise ValidationError(_("The INN has 10 or 12 digits."))
    if len(value) == 10:
        ok = _weighted(value, [2, 4, 10, 3, 5, 9, 4, 6, 8]) % 11 % 10 == int(value[9])
    else:
        n11 = _weighted(value, [7, 2, 4, 10, 3, 5, 9, 4, 6, 8]) % 11 % 10
        n12 = _weighted(value, [3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8]) % 11 % 10
        ok = n11 == int(value[10]) and n12 == int(value[11])
    if not ok:
        raise ValidationError(_("This INN has a typo: its check digit does not match."))


def validate_account(account, bik):
    """A 20-digit settlement account, checked against the bank's BIK (the
    control key uses the BIK's last three digits)."""
    if not re.fullmatch(r"\d{20}", account):
        raise ValidationError(_("The account number has 20 digits."))
    weights = [7, 1, 3] * 8
    if _weighted(bik[-3:] + account, weights) % 10 != 0:
        raise ValidationError(
            _("The account number does not match the BIK. Check both for a typo.")
        )
