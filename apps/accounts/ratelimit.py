"""Login limits: slow down and stop PIN guessing without locking out a
dormitory that shares one internet address.

Two independent limits, both kept in the shared cache (the database cache in
production, so every server worker sees the same counts). The numbers are
GlobalSettings fields that superusers change in Django admin.

Per account (the student code or staff username as typed):
    after `login_account_failures` wrong PINs in a row the account is locked
    for `login_account_lock_seconds`; each further lock lasts twice as long,
    up to `login_account_max_lock_seconds`. A successful login starts over.
    Codes that do not exist are counted exactly like real ones, so a lock
    reveals nothing about which codes exist.

Per address (apps/core/client_ip.py):
    a whole dormitory may come from one address, so typos from hundreds of
    residents must never block it. Up to `login_address_free_failures` wrong
    PINs in 15 minutes nothing happens. Beyond that, each attempt must wait a
    few seconds after the address's last failure (one more second for every
    10 extra failures, at most `login_address_max_delay_seconds`). Only
    `login_address_hourly_limit` wrong PINs in an hour block the address
    until the hour is over.

Every refusal happens before the PIN is checked, so a locked account cannot
be probed. Messages never say whether a code exists.
"""

import math
import time

from django.core.cache import cache

from apps.core.client_ip import client_ip
from apps.dorms import rules

ADDRESS_WINDOW = 15 * 60
HOUR = 60 * 60
# How long the account history (the lock level) is kept after the last failure.
ACCOUNT_MEMORY = 24 * HOUR
DELAY_STEP = 10  # one more second of waiting per 10 failures over the free amount


def _now():
    return time.time()


def _account_key(code):
    return f"login:account:{(code or '').strip().lower()}"


def _address_key(request):
    return f"login:address:{client_ip(request)}"


class Refusal:
    """Why an attempt is refused before the PIN is checked. `seconds`: how
    long to wait (None: "later")."""

    ACCOUNT_LOCKED = "account_locked"
    ADDRESS_WAIT = "address_wait"
    ADDRESS_BLOCKED = "address_blocked"

    def __init__(self, reason, seconds=None):
        self.reason, self.seconds = reason, seconds


def _address_state(request, now):
    state = cache.get(_address_key(request)) or {}
    window = [t for t in state.get("failures", []) if t > now - HOUR]
    return {"failures": window}


def _address_delay(failures, now, limits):
    recent = [t for t in failures if t > now - ADDRESS_WINDOW]
    over = len(recent) - limits.login_address_free_failures
    if over <= 0:
        return 0
    return min(limits.login_address_max_delay_seconds, math.ceil(over / DELAY_STEP))


def check(code, request):
    """A Refusal if this attempt must not even be checked, else None."""
    limits, now = rules.current(), _now()
    account = cache.get(_account_key(code)) or {}
    locked_until = account.get("locked_until", 0)
    if locked_until > now:
        return Refusal(Refusal.ACCOUNT_LOCKED, math.ceil(locked_until - now))

    failures = _address_state(request, now)["failures"]
    if len(failures) >= limits.login_address_hourly_limit:
        return Refusal(Refusal.ADDRESS_BLOCKED, math.ceil(min(failures) + HOUR - now))
    delay = _address_delay(failures, now, limits)
    if delay and failures and now < max(failures) + delay:
        return Refusal(Refusal.ADDRESS_WAIT, math.ceil(max(failures) + delay - now))
    return None


def register_failure(code, request):
    """A wrong code or PIN: count it for the account and for the address."""
    limits, now = rules.current(), _now()

    key = _account_key(code)
    account = cache.get(key) or {"failures": 0, "level": 0, "locked_until": 0}
    account["failures"] += 1
    if account["failures"] >= limits.login_account_failures:
        account["level"] += 1
        seconds = min(
            limits.login_account_lock_seconds * 2 ** (account["level"] - 1),
            limits.login_account_max_lock_seconds,
        )
        account["locked_until"] = now + seconds
        account["failures"] = 0
    cache.set(key, account, ACCOUNT_MEMORY + limits.login_account_max_lock_seconds)

    state = _address_state(request, now)
    state["failures"].append(now)
    cache.set(_address_key(request), state, HOUR)


def reset(code, request):
    """A successful login: the account starts over. The address keeps its
    count: one resident getting in says nothing about the others' attempts."""
    cache.delete(_account_key(code))


def is_locked(code, request):
    return check(code, request) is not None
