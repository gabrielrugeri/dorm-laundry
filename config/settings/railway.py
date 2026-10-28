"""Settings for the public demo on Railway (fake data only).

Railway hosts outside Russia: the demo may be unreachable from some Russian
networks and must never hold real resident data. So this settings module
refuses to start unless DEMO_MODE=true, whatever PILOT_READY says.

Everything else is production (config/settings/prod.py) plus the hosts
Railway needs: the generated *.up.railway.app domain (RAILWAY_PUBLIC_DOMAIN,
set by Railway) and the host Railway's health checks use.
"""

from django.core.exceptions import ImproperlyConfigured

from .prod import *  # noqa: F403
from .prod import ALLOWED_HOSTS, CSRF_TRUSTED_ORIGINS, DEMO_MODE, env

if not DEMO_MODE:
    raise ImproperlyConfigured(
        "Refusing to start: the Railway demo must run with DEMO_MODE=true. "
        "It is hosted outside Russia and must never hold real resident data."
    )

# Railway's health checks send this Host header (docs.railway.com/reference/healthchecks).
RAILWAY_HEALTHCHECK_HOST = "healthcheck.railway.app"

RAILWAY_PUBLIC_DOMAIN = env("RAILWAY_PUBLIC_DOMAIN", default="")
ALLOWED_HOSTS = [*ALLOWED_HOSTS, RAILWAY_HEALTHCHECK_HOST]
if RAILWAY_PUBLIC_DOMAIN:
    ALLOWED_HOSTS.append(RAILWAY_PUBLIC_DOMAIN)
    CSRF_TRUSTED_ORIGINS = [*CSRF_TRUSTED_ORIGINS, f"https://{RAILWAY_PUBLIC_DOMAIN}"]
