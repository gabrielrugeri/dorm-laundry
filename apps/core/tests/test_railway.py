"""The Railway demo: settings from Railway-style environment variables, the
DEMO_MODE guard, gunicorn on $PORT, the pre-deploy command and seed_demo's
server guards."""

import json
import os
import runpy
import subprocess
import sys
from pathlib import Path

import pytest
from django.core.management import CommandError, call_command

from apps.accounts.models import Resident

ROOT = Path(__file__).resolve().parents[3]

RAILWAY_ENV = {
    "DJANGO_READ_DOT_ENV": "false",
    "DJANGO_SETTINGS_MODULE": "config.settings.railway",
    "DJANGO_SECRET_KEY": "x" * 60,
    "DEMO_MODE": "true",
    "PORT": "8080",
    "RAILWAY_PUBLIC_DOMAIN": "dorm-laundry-demo.up.railway.app",
    "DATABASE_URL": "postgresql://postgres:secret@postgres.railway.internal:5432/railway",
}


def load_settings(**overrides):
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("DJANGO_", "DEMO_MODE", "PILOT_READY", "DATABASE_URL", "RAILWAY_"))
    }
    env.update(RAILWAY_ENV)
    env.update(overrides)
    code = (
        "import json, django; django.setup(); from django.conf import settings as s; "
        "print(json.dumps({'hosts': s.ALLOWED_HOSTS, 'csrf': s.CSRF_TRUSTED_ORIGINS, "
        "'db_engine': s.DATABASES['default']['ENGINE'], 'db_host': s.DATABASES['default']['HOST'], "
        "'cache': s.CACHES['default']['BACKEND'], 'proxy': list(s.SECURE_PROXY_SSL_HEADER), "
        "'demo': s.DEMO_MODE, 'debug': s.DEBUG}))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True
    )
    return result.returncode, result.stdout.strip().splitlines()[-1:] or [""], result.stderr


def test_railway_settings_from_railway_variables():
    code, (output,), stderr = load_settings()
    assert code == 0, stderr
    values = json.loads(output)
    assert "dorm-laundry-demo.up.railway.app" in values["hosts"]
    assert "healthcheck.railway.app" in values["hosts"]  # Railway's health checks
    assert values["csrf"] == ["https://dorm-laundry-demo.up.railway.app"]
    assert values["db_engine"] == "django.db.backends.postgresql"
    assert values["db_host"] == "postgres.railway.internal"
    assert values["cache"].endswith("DatabaseCache")
    assert values["proxy"] == [
        "HTTP_X_FORWARDED_PROTO",
        "https",
    ]  # Railway's proxy terminates HTTPS
    assert values["demo"] is True and values["debug"] is False


@pytest.mark.parametrize("pilot_ready", ["false", "true"])
def test_railway_refuses_to_run_without_demo_mode(pilot_ready):
    code, _output, stderr = load_settings(DEMO_MODE="false", PILOT_READY=pilot_ready)
    assert code != 0
    assert "Refusing to start" in stderr


def test_gunicorn_binds_to_railway_port(monkeypatch):
    monkeypatch.setenv("PORT", "8080")
    config = runpy.run_path(str(ROOT / "gunicorn.conf.py"))
    assert config["bind"] == "0.0.0.0:8080"
    assert config["workers"] == 2


def test_dockerfile_builds_everything_without_a_database():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    for step in ("tailwind.py build", "compilemessages", "collectstatic", "gettext"):
        assert step in dockerfile, step
    assert "config.settings.railway" in dockerfile
    assert 'CMD ["gunicorn", "config.wsgi"]' in dockerfile
    ignored = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    assert ".env" in ignored and "db.sqlite3*" in ignored


# --- Pre-deploy and demo data ----------------------------------------------------------


def test_predeploy_seeds_once_in_demo_mode(db, settings):
    settings.DEMO_MODE = True
    call_command("predeploy")
    count = Resident.objects.count()
    assert count > 0
    call_command("predeploy")  # every deploy runs it again
    assert Resident.objects.count() == count


def test_predeploy_adds_no_demo_data_outside_demo_mode(db, settings):
    settings.DEMO_MODE = False
    call_command("predeploy")
    assert not Resident.objects.exists()


def test_seed_demo_on_a_server_needs_demo_mode(db, settings):
    settings.IS_PRODUCTION, settings.DEMO_MODE = True, False
    with pytest.raises(CommandError, match="DEMO_MODE"):
        call_command("seed_demo")
    assert not Resident.objects.exists()


def test_seed_demo_on_a_server_refuses_published_passwords(db, settings, monkeypatch):
    settings.IS_PRODUCTION, settings.DEMO_MODE = True, True
    monkeypatch.delenv("SEED_DEMO_STAFF_PASSWORD", raising=False)
    monkeypatch.delenv("SEED_DEMO_RESIDENT_PIN", raising=False)
    with pytest.raises(CommandError, match="SEED_DEMO_STAFF_PASSWORD"):
        call_command("seed_demo")

    monkeypatch.setenv("SEED_DEMO_STAFF_PASSWORD", "a-long-private-demo-password")
    monkeypatch.setenv("SEED_DEMO_RESIDENT_PIN", "482913")
    call_command("seed_demo")
    assert Resident.objects.exists()
