"""Local development settings."""

import os

# Safe defaults so a fresh clone runs without a .env file.
os.environ.setdefault("DJANGO_SECRET_KEY", "dev-insecure-secret-key-do-not-use-in-production")
os.environ.setdefault("DJANGO_DEBUG", "true")
os.environ.setdefault("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,[::1]")

from .base import *  # noqa: E402, F403

# Same as above for dev: no collectstatic needed.
WHITENOISE_AUTOREFRESH = True
