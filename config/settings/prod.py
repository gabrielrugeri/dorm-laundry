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

DEBUG = False

# We run behind a reverse proxy (e.g. nginx) that terminates HTTPS.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env.bool("DJANGO_SECURE_SSL_REDIRECT", default=True)
# Health checks from the hosting platform may come over plain HTTP.
SECURE_REDIRECT_EXEMPT = [r"^healthz$"]
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = env.int("DJANGO_SECURE_HSTS_SECONDS", default=60 * 60 * 24 * 30)
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
