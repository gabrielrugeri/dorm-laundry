"""Setting and checking residents' PINs. Always go through these two
functions, never user.set_password()/check_password(), so every PIN is
hashed with the pepper (apps/accounts/hashers.py).
"""

from django.contrib.auth.hashers import check_password, make_password

from .hashers import ALGORITHM


def set_pin(user, pin):
    """Hash `pin` with the pepper into user.password (the caller saves)."""
    user.password = make_password(pin, hasher=ALGORITHM)
    user._password = None


def dummy_check(pin):
    """Spend the same time as a real check (unknown student codes)."""
    make_password(pin, hasher=ALGORITHM)


def is_peppered(user):
    return user.password.startswith(ALGORITHM + "$")


def check_pin(user, pin):
    """True if `pin` is the user's PIN.

    PINs set before the pepper existed are plain PBKDF2 hashes: they still
    work once, and are re-hashed with the pepper right then (no setter is
    passed to check_password, so Django never re-hashes a PIN without it).
    """
    if not user.has_usable_password() or not check_password(pin, user.password):
        return False
    if not is_peppered(user):
        set_pin(user, pin)
        user.save(update_fields=["password"])
    return True
