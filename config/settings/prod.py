"""Production settings. Every secret must come from the environment."""

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F403
from .base import DEMO_MODE, env

# The pilot gate (docs/plans/admin-and-payments.md): a production instance
# without the demo banner may hold real resident data, so it only starts when
# someone has explicitly confirmed that every pilot gate item is done.
PILOT_READY = env.bool("PILOT_READY", default=False)
if not DEMO_MODE and not PILOT_READY:
    raise ImproperlyConfigured(
        "Refusing to start: DEMO_MODE is false but PILOT_READY is not true. "
        "Real resident data needs every pilot gate item done first "
        "(docs/plans/admin-and-payments.md). For a demo with fake data, set DEMO_MODE=true."
    )

# No silent fallback to a local SQLite file outside development: on a server
# that file would live on a disk the platform may wipe (Railway does on every
# deploy), and all data would be lost. A deploy check also refuses SQLite
# itself (apps/core/checks.py).
if not env("DATABASE_URL", default=""):
    raise ImproperlyConfigured(
        "Refusing to start: DATABASE_URL is not set. Production needs PostgreSQL, "
        "e.g. postgres://user:password@host:5432/name (on Railway: ${{Postgres.DATABASE_URL}})."
    )

DEBUG = False
IS_PRODUCTION = True

# We run behind a reverse proxy (e.g. nginx) that terminates HTTPS.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env.bool("DJANGO_SECURE_SSL_REDIRECT", default=True)
# Health checks from the hosting platform may come over plain HTTP.
SECURE_REDIRECT_EXEMPT = [r"^healthz$"]
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = env.int("DJANGO_SECURE_HSTS_SECONDS", default=60 * 60 * 24 * 30)
# Only subdomains of our own host (e.g. *.laundry.example.ru), so safe to keep on.
SECURE_HSTS_INCLUDE_SUBDOMAINS = env.bool("DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS", default=True)
# The browser preload list needs the domain owner to register the domain; that
# is their decision, so it stays off and Django's reminder is silenced until then.
SECURE_HSTS_PRELOAD = env.bool("DJANGO_SECURE_HSTS_PRELOAD", default=False)
SILENCED_SYSTEM_CHECKS = [] if SECURE_HSTS_PRELOAD else ["security.W021"]
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

# One cache shared by all server workers (the login lockout counts failures
# in it). Stored in PostgreSQL: run `manage.py createcachetable` when deploying.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.db.DatabaseCache",
        "LOCATION": "django_cache",
    }
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
}
