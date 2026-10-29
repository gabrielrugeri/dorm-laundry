"""The installable app: manifest, service worker, offline page, phone meta
tags and the light/dark choice. Every name here is fake."""

import json
import re

import pytest
from django.contrib.staticfiles import finders
from django.urls import reverse

from apps.accounts.models import UserPreferences

MANIFEST = reverse("core:manifest")
SW = reverse("core:service_worker")
OFFLINE = reverse("core:offline")
THEME = reverse("accounts:set_theme")


def test_manifest_describes_an_installable_app(client, db):
    response = client.get(MANIFEST)
    assert response["Content-Type"] == "application/manifest+json"
    data = json.loads(response.content)
    assert data["display"] == "standalone"
    assert data["start_url"] == "/" and data["scope"] == "/"
    assert data["theme_color"] and data["background_color"]
    sizes = {(icon["sizes"], icon.get("purpose", "any")) for icon in data["icons"]}
    assert {("192x192", "any"), ("512x512", "any"), ("512x512", "maskable")} <= sizes
    for icon in data["icons"]:
        name = icon["src"].removeprefix("/static/")
        assert finders.find(name), name  # served from our own server


def test_apple_touch_icon_exists():
    assert finders.find("icons/apple-touch-icon.png")


def test_pages_link_the_manifest_and_phone_settings(client, resident):
    client.force_login(resident.user)
    html = client.get(reverse("bookings:mine")).content.decode()
    assert f'rel="manifest" href="{MANIFEST}"' in html
    assert 'rel="apple-touch-icon"' in html
    assert "viewport-fit=cover" in html
    assert 'name="apple-mobile-web-app-capable" content="yes"' in html
    assert "user-scalable=no" not in html  # pinch zoom must stay possible


def test_service_worker_caches_only_the_offline_page(client, db):
    response = client.get(SW)
    assert response["Content-Type"].startswith("text/javascript")
    assert "no-cache" in response["Cache-Control"]
    body = response.content.decode()
    precache = json.loads(re.search(r"var PRECACHE = (\[.*?\]);", body).group(1))
    assert precache[0] == OFFLINE
    assert all(url == OFFLINE or url.startswith("/static/") for url in precache)
    assert 'credentials: "omit"' in body
    for personal in ("/balance", "/bookings", "/manage", "/account"):
        assert personal not in body


def test_offline_page_has_no_personal_data(client, resident):
    client.force_login(resident.user)
    response = client.get(OFFLINE)
    assert response.status_code == 200
    html = response.content.decode()
    assert resident.full_name not in html and resident.room not in html
    assert "csrfmiddlewaretoken" not in html


def test_csp_allows_our_own_manifest_and_worker(client, db):
    csp = client.get(OFFLINE)["Content-Security-Policy"]
    assert "manifest-src 'self'" in csp and "worker-src 'self'" in csp


def test_install_guide_is_on_the_page_but_hidden(client, resident):
    client.force_login(resident.user)
    html = client.get(reverse("bookings:mine")).content.decode()
    assert '<section id="install-guide" hidden' in html
    for variant in ("ios", "android", "in-app"):
        assert f'data-install-variant="{variant}" hidden' in html


# --- Light / dark ------------------------------------------------------------------


def test_theme_follows_the_phone_by_default(client, resident):
    client.force_login(resident.user)
    assert "data-theme" not in client.get(reverse("bookings:mine")).content.decode()[:300]


@pytest.mark.parametrize("choice", ["light", "dark"])
def test_theme_choice_is_saved_for_the_user(client, resident, choice):
    client.force_login(resident.user)
    response = client.post(THEME, {"theme": choice, "next": "/bookings/"})
    assert response.status_code == 302 and response.url == "/bookings/"
    assert response.cookies["theme"].value == choice
    assert UserPreferences.objects.get(user=resident.user).theme == choice
    # Another device (no cookie) gets the saved choice too.
    client.cookies.pop("theme")
    html = client.get(reverse("bookings:mine")).content.decode()
    assert f'data-theme="{choice}"' in html


def test_theme_without_login_uses_the_cookie(client, db):
    client.post(THEME, {"theme": "dark", "next": "/account/login/"})
    assert 'data-theme="dark"' in client.get(reverse("accounts:login")).content.decode()
    assert not UserPreferences.objects.exists()


def test_unknown_theme_and_foreign_redirects_are_refused(client, resident):
    client.force_login(resident.user)
    response = client.post(THEME, {"theme": "neon", "next": "https://evil.example/"})
    assert response.url == "/"
    assert UserPreferences.objects.get(user=resident.user).theme == "system"
