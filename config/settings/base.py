"""Settings shared by every environment.

Values that differ between machines (secrets, hosts, database) come from
environment variables. In development they can be put in a `.env` file at the
project root; see `.env.example`.
"""

from pathlib import Path

import environ
from django.utils.translation import gettext_lazy as _

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("DJANGO_SECRET_KEY")
DEBUG = env.bool("DJANGO_DEBUG", default=False)
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=[])
CSRF_TRUSTED_ORIGINS = env.list("DJANGO_CSRF_TRUSTED_ORIGINS", default=[])

INSTALLED_APPS = [
    "apps.core.admin_config.SuperuserAdminConfig",  # Django admin, superusers only
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "whitenoise.runserver_nostatic",
    "django.contrib.staticfiles",
    # Project apps
    "apps.core",
    "apps.accounts",
    "apps.dorms",
    "apps.bookings",
    "apps.ledger",
    "apps.keylog",
    "apps.audit",
    "apps.manage",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.template.context_processors.i18n",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.ledger.context_processors.resident_balance",
                "apps.accounts.context_processors.user_roles",
            ],
        },
    },
]

# Database: DATABASE_URL, e.g. sqlite:///db.sqlite3 or postgres://user:pass@host:5432/name
# An empty or unset DATABASE_URL means the local SQLite file.
DATABASE_URL = env("DATABASE_URL", default="") or f"sqlite:///{BASE_DIR / 'db.sqlite3'}"
DATABASES = {"default": env.db_url_config(DATABASE_URL)}
if DATABASES["default"]["ENGINE"] == "django.db.backends.sqlite3":
    # Take the write lock at the start of each transaction, so concurrent
    # writers wait for each other instead of failing with "database is locked".
    DATABASES["default"].setdefault("OPTIONS", {})["transaction_mode"] = "IMMEDIATE"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_USER_MODEL = "accounts.User"
# Residents log in with student code + PIN; staff with username + password.
AUTHENTICATION_BACKENDS = [
    "apps.accounts.backends.ResidentBackend",
    "django.contrib.auth.backends.ModelBackend",
]
# The dormitory residents log in to, while the pilot has only one.
DEFAULT_DORMITORY_SLUG = env("DEFAULT_DORMITORY_SLUG", default="demo")

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "core:home"
LOGOUT_REDIRECT_URL = "accounts:login"
# Activation links (Django's password-reset tokens) stay valid for 7 days.
PASSWORD_RESET_TIMEOUT = 60 * 60 * 24 * 7
# After this many failed logins for one student code from one IP address,
# login is blocked for LOGIN_LOCKOUT_SECONDS.
LOGIN_MAX_FAILURES = 5
LOGIN_LOCKOUT_SECONDS = 15 * 60

# Staff passwords (residents use PINs, see apps/accounts/validators.py).
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Internationalization. Russian is the default; English is the alternative.
LANGUAGE_CODE = "ru"
LANGUAGES = [
    ("ru", _("Russian")),
    ("en", _("English")),
]
LOCALE_PATHS = [BASE_DIR / "locale"]
USE_I18N = True

# Time: the database stores UTC; display uses the dormitory's timezone.
TIME_ZONE = "Europe/Moscow"
USE_TZ = True

# Static files are served by our own server (WhiteNoise). No CDNs.
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
