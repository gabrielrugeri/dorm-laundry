"""Test settings, used by pytest (see pyproject.toml).

Uses SQLite unless DATABASE_URL is set; CI also runs the suite on PostgreSQL.
"""

import os

os.environ.setdefault("DJANGO_SECRET_KEY", "test-secret-key")
os.environ.setdefault("DJANGO_ALLOWED_HOSTS", "testserver,localhost")

from .base import *  # noqa: E402, F403

# Hashing passwords properly is slow; tests don't need it.
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# Serve static files from the app directories without needing collectstatic.
WHITENOISE_AUTOREFRESH = True
