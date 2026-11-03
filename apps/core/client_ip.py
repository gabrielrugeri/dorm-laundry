"""The address a request really comes from, for login limits.

Behind a reverse proxy, REMOTE_ADDR is the proxy (or empty, with nginx on a
unix socket). Headers sent by the client itself can say anything, so only one
header is trusted: the one OUR proxy sets and overwrites on every request.

- CLIENT_IP_HEADER unset (development): REMOTE_ADDR.
- Railway: "X-Real-IP", which Railway's public edge sets to the connecting
  address and overwrites if the client sent one
  (docs.railway.com/networking/public-networking/specs-and-limits).
- Our nginx (deploy/nginx/dorm-laundry.conf): "X-Real-IP", set with
  `proxy_set_header X-Real-IP $remote_addr;`, which replaces any client copy.

X-Forwarded-For is never read: proxies append to whatever the client sent,
so picking the right entry depends on the exact chain of proxies. One header
that the last proxy overwrites is simpler and cannot be spoofed.
"""

import ipaddress

from django.conf import settings

UNKNOWN = "unknown"


def _valid(value):
    try:
        return str(ipaddress.ip_address(value.strip()))
    except ValueError:
        return None


def client_ip(request):
    """The client's address as text, or "unknown"."""
    if request is None:
        return UNKNOWN
    header = getattr(settings, "CLIENT_IP_HEADER", "")
    if header:
        meta_key = "HTTP_" + header.upper().replace("-", "_")
        value = _valid(request.META.get(meta_key, ""))
        if value:
            return value
    return _valid(request.META.get("REMOTE_ADDR", "")) or UNKNOWN
