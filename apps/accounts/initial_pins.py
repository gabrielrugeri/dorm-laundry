"""First-time PINs from the date of birth (the residents import).

The administration provides each resident's date of birth once, in the
import file. The first-time PIN is the date as DDMMYY (5 March 2004 → 050304).
The date is used only to derive that PIN and is then thrown away: there is no
field for it, it is masked in the preview, and it never reaches the session,
the history or the logs. Only the PIN's hash is kept, in user.password, with
the pepper like every PIN.

Rules:
- The first-time PIN is valid for `initial_pin_days` (GlobalSettings, 14),
  checked at every login (`is_expired`), so it stays correct even if the
  clean-up (`expire_old`, `manage.py expire_initial_pins`) never runs.
- After logging in with it the resident must choose their own PIN before
  anything else (apps/accounts/middleware.py); the new PIN follows the normal
  rules and must differ from the first-time one. Only the first-time PIN is
  exempt from the "too easy" rule (a date can be 111111).
- No date: no first-time PIN; the resident gets a login link instead.

Hashing: between preview and confirm only `pepper(PIN)` (HMAC with the server
secret) is kept. On confirm it is finished with the PIN hasher at
INITIAL_PIN_ITERATIONS, fewer rounds than a chosen PIN, so an import of a few
hundred residents finishes within one request. The first-time PIN is
temporary and the pepper is the main protection (docs/SECURITY.md).
"""

import re
from datetime import date, timedelta

from django.contrib.auth.hashers import get_hasher
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.audit.services import record

from .hashers import ALGORITHM, pepper

INITIAL_PIN_ITERATIONS = 20_000
# Dates of birth that make sense for a resident on the day of the import.
YOUNGEST, OLDEST = 14, 100

_FORMATS = (
    (re.compile(r"(\d{2})\.(\d{2})\.(\d{4})"), "dmy"),  # 05.03.2004
    (re.compile(r"(\d{4})-(\d{2})-(\d{2})"), "ymd"),  # 2004-03-05
    (re.compile(r"(\d{2})/(\d{2})/(\d{4})"), "dmy"),  # 05/03/2004
)


class BadDate(ValueError):
    """The value is not a date we accept; the message never repeats it."""


def parse_birth_date(text, today):
    """A date of birth in DD.MM.YYYY, YYYY-MM-DD or DD/MM/YYYY, or BadDate.
    Nothing is guessed: Excel day numbers, two-digit years, American
    month/day order, impossible and implausible dates are all refused."""
    text = (text or "").strip()
    # Excel shows dates as day numbers (5 March 2004 is 38051) when the
    # column is not formatted as text.
    if re.fullmatch(r"\d{5}(\.0+)?", text):
        raise BadDate(_("the date of birth looks like an Excel number: format the column as text"))
    for pattern, order in _FORMATS:
        match = pattern.fullmatch(text)
        if not match:
            continue
        a, b, c = (int(part) for part in match.groups())
        day, month, year = (a, b, c) if order == "dmy" else (c, b, a)
        if order == "dmy" and "/" in text and month > 12 and day <= 12:
            raise BadDate(_("the date of birth looks like month/day: use DD.MM.YYYY"))
        try:
            born = date(year, month, day)
        except ValueError:
            raise BadDate(_("the date of birth does not exist")) from None
        age = today.year - born.year - ((today.month, today.day) < (born.month, born.day))
        if not YOUNGEST <= age <= OLDEST:
            raise BadDate(_("the date of birth is not plausible for a resident"))
        return born
    raise BadDate(_("the date of birth must look like 05.03.2004 or 2004-03-05"))


def pin_from_date(born):
    return born.strftime("%d%m%y")


def digest_for(born):
    """What the import keeps between preview and confirm: never the date."""
    return pepper(pin_from_date(born))


def _encode(digest):
    hasher = get_hasher(ALGORITHM)
    return hasher.encode_peppered(digest, hasher.salt(), INITIAL_PIN_ITERATIONS)


def is_activated(resident):
    """Has chosen their own PIN (and so is never touched by an import)."""
    return resident.user.has_usable_password() and not resident.must_change_pin


def set_initial_pin(*, actor, resident, digest, days, now=None):
    """Give `resident` a first-time PIN (from its digest), valid for `days`.
    Recorded in the history without the date or the PIN."""
    now = now or timezone.now()
    user = resident.user
    user.password = _encode(digest)
    user.save(update_fields=["password"])
    resident.must_change_pin = True
    resident.initial_pin_expires_at = now + timedelta(days=days)
    resident.save(update_fields=["must_change_pin", "initial_pin_expires_at"])
    record(
        actor=actor,
        action="resident.initial_pin",
        target=resident,
        after={"initial_pin_expires_at": resident.initial_pin_expires_at.isoformat()},
    )


def is_expired(resident, now=None):
    now = now or timezone.now()
    expires = resident.initial_pin_expires_at
    return resident.must_change_pin and (expires is None or expires <= now)


def clear(resident):
    """The resident chose their own PIN: the first-time one is gone."""
    if resident.must_change_pin or resident.initial_pin_expires_at:
        resident.must_change_pin = False
        resident.initial_pin_expires_at = None
        resident.save(update_fields=["must_change_pin", "initial_pin_expires_at"])


def expire_old(now=None):
    """Delete the hashes of expired first-time PINs. Returns how many. Login
    refuses expired ones anyway; this only removes what is no longer needed."""
    from .models import Resident

    now = now or timezone.now()
    count = 0
    expired = Resident.objects.filter(
        must_change_pin=True, initial_pin_expires_at__lte=now
    ).select_related("user")
    for resident in expired:
        if resident.user.has_usable_password():
            resident.user.set_unusable_password()
            resident.user.save(update_fields=["password"])
            count += 1
    return count
