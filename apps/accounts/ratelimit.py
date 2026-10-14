"""Block login for a while after repeated failures (guessing PINs).

Failures are counted per (student code, client IP) in Django's cache. Unknown
codes are counted exactly like known ones, so a lockout reveals nothing about
whether a code exists.

The default cache is per process: with several server workers each one counts
separately. That is acceptable for the pilot; a shared cache (database or
Redis) makes the limit exact. Behind a reverse proxy, configure it to pass the
real client address in REMOTE_ADDR.
"""

from django.conf import settings
from django.core.cache import cache


def _keys(code, request):
    ip = request.META.get("REMOTE_ADDR", "") if request else ""
    base = f"login:{code.strip().lower()}:{ip}"
    return f"{base}:failures", f"{base}:locked"


def is_locked(code, request):
    return cache.get(_keys(code, request)[1]) is not None


def register_failure(code, request):
    failures_key, locked_key = _keys(code, request)
    timeout = settings.LOGIN_LOCKOUT_SECONDS
    cache.add(failures_key, 0, timeout)
    failures = cache.incr(failures_key)
    if failures >= settings.LOGIN_MAX_FAILURES:
        cache.set(locked_key, True, timeout)
        cache.delete(failures_key)


def reset(code, request):
    cache.delete_many(_keys(code, request))
