import re

from django.urls import reverse

# src="..." or href="..." pointing at another host (absolute or protocol-relative URL).
EXTERNAL_URL = re.compile(r'(?:src|href)\s*=\s*["\'](?:https?:)?//', re.IGNORECASE)


def assert_local_only(response):
    assert response.status_code == 200
    assert not EXTERNAL_URL.search(response.content.decode())


def test_login_page_loads_nothing_from_third_party_hosts(client, db):
    """Users in Russia may not reach CDNs; every asset must come from our server."""
    assert_local_only(client.get(reverse("accounts:login")))


def test_home_loads_nothing_from_third_party_hosts(client, resident):
    client.force_login(resident.user)
    assert_local_only(client.get(reverse("core:home")))
