"""Deployment readiness (provider-neutral): health check, demo banner and
noindex, CSP, request size limit, production cache and the pilot start guard."""

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from django.db import DatabaseError
from django.urls import reverse

ROOT = Path(__file__).resolve().parents[3]
LOGIN = reverse("accounts:login")


# --- /healthz ------------------------------------------------------------------------


def test_healthz_is_public_and_checks_the_database(client, db):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_healthz_reports_a_broken_database(client, db, monkeypatch):
    from apps.core import views

    def broken_cursor():
        raise DatabaseError("down")

    with monkeypatch.context() as patch:  # only for this request, not for test teardown
        patch.setattr(views.connection, "cursor", broken_cursor)
        assert client.get("/healthz").status_code == 503


# --- Demo mode -----------------------------------------------------------------------


def test_demo_banner_noindex_and_robots(client, db, settings):
    settings.DEMO_MODE = True
    client.cookies["django_language"] = "en"
    response = client.get(LOGIN)
    html = response.content.decode()
    assert "Demo: all names and data here are made up" in html
    assert '<meta name="robots" content="noindex, nofollow">' in html
    assert response["X-Robots-Tag"] == "noindex, nofollow"
    assert client.get("/robots.txt").content.decode() == "User-agent: *\nDisallow: /\n"


def test_no_banner_outside_demo_mode(client, db, settings):
    settings.DEMO_MODE = False
    response = client.get(LOGIN)
    assert "noindex" not in response.content.decode()
    assert "X-Robots-Tag" not in response
    assert "Disallow: /manage/" in client.get("/robots.txt").content.decode()


# --- Content-Security-Policy ---------------------------------------------------------


def test_every_page_has_a_strict_csp(client, resident):
    for url in (LOGIN, "/healthz"):
        csp = client.get(url)["Content-Security-Policy"]
        assert "default-src 'self'" in csp and "script-src 'self'" in csp
        assert "unsafe-inline" not in csp
    client.force_login(resident.user)
    assert "unsafe-inline" not in client.get("/")["Content-Security-Policy"]


def test_django_admin_allows_inline_styles_only(client, admin_user):
    client.force_login(admin_user)
    csp = client.get("/admin/")["Content-Security-Policy"]
    assert "style-src 'self' 'unsafe-inline'" in csp
    assert "script-src 'self';" in csp


def test_templates_have_no_inline_scripts_or_handlers():
    """The CSP would block them, so a page would silently stop working."""
    inline_script = re.compile(r"<script(?![^>]*\bsrc=)[^>]*>", re.IGNORECASE)
    handler = re.compile(r"\son[a-z]+\s*=", re.IGNORECASE)
    offenders = []
    for path in (ROOT / "templates").rglob("*.html"):
        text = path.read_text(encoding="utf-8")
        if inline_script.search(text) or handler.search(text):
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []


# --- Request size --------------------------------------------------------------------


def test_requests_above_the_hard_ceiling_are_refused(client, db, settings):
    settings.MAX_UPLOAD_BYTES_HARD = 1000
    response = client.post(LOGIN, data="x" * 2000, content_type="text/plain")
    assert response.status_code == 413
    assert client.post(LOGIN, data="x" * 10, content_type="text/plain").status_code != 413


# --- Production settings (run in a separate process, as on a server) -----------------


def load_prod_settings(**env_vars):
    """Import config.settings.prod with these environment variables and return
    (exit code, output)."""
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("DJANGO_", "DEMO_MODE", "PILOT_READY", "DATABASE_URL"))
    }
    env.update(
        DJANGO_READ_DOT_ENV="false",  # a developer's local .env must not change the result
        DJANGO_SETTINGS_MODULE="config.settings.prod",
        DJANGO_SECRET_KEY="x" * 60,
        DJANGO_ALLOWED_HOSTS="demo.example.org",
        DATABASE_URL="sqlite:///:memory:",
        **env_vars,
    )
    code = (
        "import django; django.setup(); from django.conf import settings; "
        "print(settings.CACHES['default']['BACKEND'], settings.SECURE_REDIRECT_EXEMPT)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True
    )
    return result.returncode, result.stdout + result.stderr


def test_production_runs_in_demo_mode_with_a_shared_cache():
    code, output = load_prod_settings(DEMO_MODE="true")
    assert code == 0, output
    assert "DatabaseCache" in output
    assert "^healthz$" in output


@pytest.mark.parametrize("pilot_ready", [None, "false"])
def test_production_refuses_to_start_without_demo_mode_or_pilot_ready(pilot_ready):
    extra = {"DEMO_MODE": "false"}
    if pilot_ready is not None:
        extra["PILOT_READY"] = pilot_ready
    code, output = load_prod_settings(**extra)
    assert code != 0
    assert "Refusing to start" in output


def test_production_starts_without_demo_mode_once_pilot_ready():
    code, output = load_prod_settings(DEMO_MODE="false", PILOT_READY="true")
    assert code == 0, output
