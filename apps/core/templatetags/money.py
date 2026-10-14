"""Money in templates: {% load money %} … {{ amount|rub }} or {{ amount|rub_signed }}."""

from django import template
from django.utils.translation import gettext as _

register = template.Library()


@register.filter
def rub(amount):
    """50 -> "50 RUB" (in Russian: "50 ₽")."""
    return _("%(amount)s RUB") % {"amount": amount}


@register.filter
def rub_signed(amount):
    """Ledger amounts: 200 -> "+200 RUB", -50 -> "−50 RUB"."""
    sign = "+" if amount > 0 else "−" if amount < 0 else ""
    return sign + rub(abs(amount))
