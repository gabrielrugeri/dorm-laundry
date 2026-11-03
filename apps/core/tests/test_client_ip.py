"""The client address for login limits: only the header our proxy overwrites."""

import pytest
from django.test import RequestFactory

from apps.core.client_ip import client_ip


@pytest.fixture
def behind_proxy(settings):
    settings.CLIENT_IP_HEADER = "X-Real-IP"


def request(**meta):
    return RequestFactory().get("/", **meta)


def test_development_uses_the_connection_address(settings):
    settings.CLIENT_IP_HEADER = ""
    assert client_ip(request(REMOTE_ADDR="10.1.2.3", HTTP_X_REAL_IP="1.1.1.1")) == "10.1.2.3"


def test_behind_the_proxy_uses_its_header(behind_proxy):
    assert client_ip(request(REMOTE_ADDR="", HTTP_X_REAL_IP="203.0.113.7")) == "203.0.113.7"


def test_a_spoofed_x_forwarded_for_is_ignored(behind_proxy):
    """A client can put anything in X-Forwarded-For; it is never read."""
    spoofed = request(
        REMOTE_ADDR="",
        HTTP_X_FORWARDED_FOR="198.51.100.1, 198.51.100.2",
        HTTP_X_REAL_IP="203.0.113.7",
    )
    assert client_ip(spoofed) == "203.0.113.7"
    only_spoofed = request(REMOTE_ADDR="10.0.0.5", HTTP_X_FORWARDED_FOR="198.51.100.1")
    assert client_ip(only_spoofed) == "10.0.0.5"


def test_garbage_in_the_header_is_not_an_address(behind_proxy):
    assert client_ip(request(REMOTE_ADDR="10.0.0.5", HTTP_X_REAL_IP="not-an-ip")) == "10.0.0.5"
    assert client_ip(request(REMOTE_ADDR="", HTTP_X_REAL_IP="")) == "unknown"


def test_nginx_overwrites_the_header_with_the_real_address():
    from pathlib import Path

    conf = (Path(__file__).resolve().parents[3] / "deploy/nginx/dorm-laundry.conf").read_text()
    assert "proxy_set_header X-Real-IP $remote_addr;" in conf
