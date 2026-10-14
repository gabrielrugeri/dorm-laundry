import re

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

PIN_LENGTH = 6


def _is_trivial(pin):
    """All the same digit (000000) or a straight run up or down (123456, 987654)."""
    if len(set(pin)) == 1:
        return True
    steps = {int(b) - int(a) for a, b in zip(pin, pin[1:], strict=False)}
    return steps in ({1}, {-1})


def validate_pin(pin):
    """A resident's PIN is exactly 6 digits and not trivially guessable."""
    if not re.fullmatch(rf"\d{{{PIN_LENGTH}}}", pin or ""):
        raise ValidationError(_("The PIN must be exactly 6 digits."), code="pin_format")
    if _is_trivial(pin):
        raise ValidationError(
            _("This PIN is too easy to guess. Avoid repeated or consecutive digits."),
            code="pin_trivial",
        )
