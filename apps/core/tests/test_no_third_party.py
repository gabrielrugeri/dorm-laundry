import re

from django.urls import reverse

# src="..." or href="..." pointing at another host (absolute or protocol-relative URL).
EXTERNAL_URL = re.compile(r'(?:src|href)\s*=\s*["\'](?:https?:)?//', re.IGNORECASE)


def test_home_loads_nothing_from_third_party_hosts(client):
    """Users in Russia may not reach CDNs; every asset must come from our server."""
    html = client.get(reverse("core:home")).content.decode()
    assert not EXTERNAL_URL.search(html)
