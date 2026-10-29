import re

from django.urls import reverse

# Something the browser would *load* from another host: src="..." on any tag,
# or href="..." on <link> (stylesheets, icons, manifests). Plain <a href> links
# to other sites (e.g. "Add to Google Calendar") load nothing until clicked.
EXTERNAL_URL = re.compile(
    r'(?:\bsrc\s*=|<link\b[^>]*\bhref\s*=)\s*["\'](?:https?:)?//', re.IGNORECASE
)


def assert_local_only(response):
    assert response.status_code == 200
    assert not EXTERNAL_URL.search(response.content.decode())


def test_login_page_loads_nothing_from_third_party_hosts(client, db):
    """Users in Russia may not reach CDNs; every asset must come from our server."""
    assert_local_only(client.get(reverse("accounts:login")))


def test_home_loads_nothing_from_third_party_hosts(client, resident):
    client.force_login(resident.user)
    assert_local_only(client.get(reverse("core:home")))
