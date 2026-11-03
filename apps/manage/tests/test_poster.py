"""The printable poster for residents and the help text it shows."""

import re

import pytest
from django.urls import reverse

from apps.accounts import roles
from apps.audit.models import AuditEvent
from apps.keylog.tests.test_services import make_staff

POSTER = reverse("manage:poster")
HELP = reverse("manage:help_contact")


@pytest.fixture
def boss_client(client, dormitory):
    client.force_login(make_staff(dormitory, "boss", role=roles.ADMIN))
    return client


def test_poster_is_for_admins_only(client, dormitory, resident):
    assert client.get(POSTER).status_code == 302  # anonymous: log in first
    client.force_login(resident.user)
    assert client.get(POSTER).status_code == 403
    client.force_login(make_staff(dormitory, "keys", role=roles.MANAGER))
    assert client.get(POSTER).status_code == 403
    assert client.get(HELP).status_code == 403


@pytest.mark.parametrize(
    "lang, words",
    [
        ("ru", ["Записывайтесь на стирку с телефона", "ДДММГГ", "050304", "На экран"]),
        ("en", ["Book the washing machine from your phone", "DDMMYY", "050304", "Home Screen"]),
    ],
)
def test_poster_in_each_language(boss_client, lang, words):
    html = boss_client.get(POSTER, {"lang": lang}).content.decode()
    assert f'<html lang="{lang}"' in html
    for word in words:
        assert word in html


def test_qr_code_is_an_svg_made_here_pointing_to_the_app(boss_client, dormitory):
    html = boss_client.get(POSTER).content.decode()
    assert re.search(r"<svg[^>]*viewBox", html)
    assert "http://testserver/" in html
    # Nothing from elsewhere: only our own static files, no inline scripts or styles.
    for url in re.findall(r'(?:src|href)="([^"]+)"', html):
        assert url.startswith(("/", "?", "#")), url
    assert "<style" not in html
    assert re.findall(r"<script(?![^>]*src=)", html) == []
    assert dormitory.name in html


def test_help_contact_is_edited_under_settings_and_printed(boss_client, dormitory):
    settings_page = boss_client.get(reverse("manage:settings")).content.decode()
    assert HELP in settings_page and POSTER in settings_page
    response = boss_client.post(HELP, {"help_contact": "Room 105, Mon–Fri 18:00–20:00"})
    assert response.status_code == 302
    dormitory.refresh_from_db()
    assert dormitory.help_contact == "Room 105, Mon–Fri 18:00–20:00"
    assert "Room 105" in boss_client.get(POSTER).content.decode()
    event = AuditEvent.objects.get(action="dormitory.help_contact")
    assert event.after["help_contact"] == "Room 105, Mon–Fri 18:00–20:00"


def test_without_help_contact_the_poster_says_ask_the_administration(boss_client):
    html = boss_client.get(POSTER, {"lang": "en"}).content.decode()
    assert "Ask the dormitory administration." in html


def test_help_text_is_escaped(boss_client):
    boss_client.post(HELP, {"help_contact": "<script>alert(1)</script>"})
    html = boss_client.get(POSTER).content.decode()
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_poster_says_how_long_the_first_pin_works(boss_client):
    from apps.dorms.models import GlobalSettings

    GlobalSettings.objects.filter(pk=1).update(initial_pin_days=10)
    html = boss_client.get(POSTER, {"lang": "en"}).content.decode()
    assert "only for the first 10 days" in html
