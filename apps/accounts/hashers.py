"""Residents' PINs are hashed with a server-side secret (the "pepper").

A PIN has only a million possible values, so a stolen database alone would
let anyone try them all against each hash. The pepper (PIN_PEPPER, an
environment variable, never in the database or the repository) is mixed in
with HMAC-SHA256 before the normal PBKDF2 hashing: without it the hashes
cannot be checked at all.

Stored hashes start with "pin_pbkdf2_sha256$", so Django picks this hasher
for them automatically. Staff passwords keep Django's normal hasher. Losing
or changing PIN_PEPPER makes every PIN invalid: residents then need a new
login link (docs/SECURITY.md).
"""

import hashlib
import hmac

from django.conf import settings
from django.contrib.auth.hashers import PBKDF2PasswordHasher

ALGORITHM = "pin_pbkdf2_sha256"


def pepper(pin):
    key = settings.PIN_PEPPER.encode()
    return hmac.new(key, str(pin).encode(), hashlib.sha256).hexdigest()


class PinHasher(PBKDF2PasswordHasher):
    algorithm = ALGORITHM

    @property
    def iterations(self):
        # Fewer rounds in tests only (config/settings/test.py).
        return getattr(settings, "PIN_HASH_ITERATIONS", None) or PBKDF2PasswordHasher.iterations

    def encode(self, password, salt, iterations=None):
        return super().encode(pepper(password), salt, iterations)

    def encode_peppered(self, peppered, salt, iterations=None):
        """Finish a hash from `pepper(pin)` computed earlier (the residents
        import keeps only that between preview and confirm, never the PIN)."""
        return super().encode(peppered, salt, iterations)
