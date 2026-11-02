"""The pilot's server files in deploy/: they must agree with the app's
settings and keep the safety rules (docs/DEPLOYMENT.md)."""

import os
import re
import runpy
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from django.conf import settings

ROOT = Path(__file__).resolve().parents[3]
DEPLOY = ROOT / "deploy"
SCRIPTS = sorted((DEPLOY / "scripts").glob("*.sh"))


def read(relative):
    return (DEPLOY / relative).read_text(encoding="utf-8")


def test_nginx_upload_limit_equals_the_apps_hard_limit():
    limit = re.search(r"client_max_body_size\s+(\d+)m;", read("nginx/dorm-laundry.conf"))
    assert int(limit.group(1)) * 1024 * 1024 == settings.MAX_UPLOAD_BYTES_HARD
    assert f"MAX_UPLOAD_BYTES_HARD={settings.MAX_UPLOAD_BYTES_HARD}" in read("env.example")


def test_nginx_never_serves_private_files_and_forwards_https():
    conf = read("nginx/dorm-laundry.conf")
    locations = re.findall(r"location\s+([^\s{]+)", conf)
    assert not any("private" in location or "media" in location for location in locations)
    assert "alias /srv/dorm-laundry/private_media" not in conf
    assert "proxy_set_header X-Forwarded-Proto $scheme;" in conf
    assert "return 301 https://" in conf


def test_app_service_runs_gunicorn_on_the_socket_nginx_uses():
    service = read("systemd/dorm-laundry.service")
    socket = re.search(r"GUNICORN_BIND=unix:(\S+)", service).group(1)
    assert f"proxy_pass http://unix:{socket};" in read("nginx/dorm-laundry.conf")
    assert "ExecStart=/srv/dorm-laundry/venv/bin/gunicorn config.wsgi" in service
    assert "Environment=DJANGO_SETTINGS_MODULE=config.settings.prod" in service
    assert "ProtectSystem=strict" in service
    assert "ReadWritePaths=/srv/dorm-laundry/private_media" in service
    assert "OnFailure=dorm-laundry-alert@%n.service" in service


def test_gunicorn_uses_the_socket_when_told(monkeypatch):
    monkeypatch.setenv("GUNICORN_BIND", "unix:/run/dorm-laundry/gunicorn.sock")
    assert runpy.run_path(str(ROOT / "gunicorn.conf.py"))["bind"] == (
        "unix:/run/dorm-laundry/gunicorn.sock"
    )


def test_backup_runs_nightly_and_alerts_on_failure():
    timer = read("systemd/dorm-laundry-backup.timer")
    assert "OnCalendar=*-*-* 03:30:00 Europe/Moscow" in timer and "Persistent=true" in timer
    assert "OnFailure=dorm-laundry-alert@%n.service" in read("systemd/dorm-laundry-backup.service")


def test_backup_is_encrypted_before_it_leaves_the_server():
    script = read("scripts/backup.sh")
    assert "pg_dump" in script and "PRIVATE_MEDIA_ROOT" in script
    encrypt = script.index("age --recipient")
    upload = script.index("rclone copy")
    assert encrypt < upload  # nothing unencrypted goes off-site
    assert "umask 077" in script


def test_restore_is_a_test_unless_explicitly_told():
    script = read("scripts/restore.sh")
    assert 'mode="${3:-test}"' in script
    assert "dorm_laundry_restore_test" in script
    assert "--into-production" in script and "Type the database name" in script


@pytest.mark.parametrize("script", SCRIPTS, ids=[s.name for s in SCRIPTS])
def test_scripts_stop_on_errors_and_are_executable(script):
    text = script.read_text(encoding="utf-8")
    assert text.startswith("#!/usr/bin/env bash\n")
    assert "set -euo pipefail" in text
    mode = subprocess.run(
        ["git", "ls-files", "--stage", str(script.relative_to(ROOT))],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=True,
    ).stdout
    assert mode.startswith("100755"), "mark it executable: git update-index --chmod=+x"


@pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")
@pytest.mark.parametrize("script", SCRIPTS, ids=[s.name for s in SCRIPTS])
def test_scripts_have_valid_syntax(script):
    # Raw bytes through stdin: works where bash cannot read Windows paths, and
    # keeps the LF line endings (text mode would send CRLF on Windows).
    result = subprocess.run(["bash", "-n"], input=script.read_bytes(), capture_output=True)
    assert result.returncode == 0, result.stderr.decode(errors="replace")


def test_no_real_secrets_in_the_examples():
    for name in ("env.example", "backup.env.example"):
        text = read(name)
        assert "example.ru" in text  # placeholders only
        assert "PILOT_READY=false" in text or name == "backup.env.example"
        assert "BEGIN" not in text and "AGE-SECRET-KEY" not in text


def test_production_check_is_clean_so_deploy_can_stop_on_warnings():
    """deploy.sh runs `check --deploy --fail-level WARNING`."""
    assert "check --deploy --fail-level WARNING" in read("scripts/deploy.sh")
    result = subprocess.run(
        [
            sys.executable,
            "manage.py",
            "check",
            "--deploy",
            "--fail-level",
            "WARNING",
        ],
        capture_output=True,
        text=True,
        cwd=ROOT,
        env={
            **os.environ,
            "DJANGO_SETTINGS_MODULE": "config.settings.prod",
            "DJANGO_READ_DOT_ENV": "false",
            "DJANGO_SECRET_KEY": "a" * 20 + "test-only-not-a-real-secret-" + "b" * 30,
            "DEMO_MODE": "false",
            "PILOT_READY": "true",
            "DJANGO_ALLOWED_HOSTS": "laundry.example.ru",
            "DATABASE_URL": "sqlite:///:memory:",
        },
    )
    assert result.returncode == 0, result.stdout + result.stderr
