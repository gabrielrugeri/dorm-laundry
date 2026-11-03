"""Deployment checks of our own, run by `manage.py check --deploy` (CI, the
Railway image job and deploy/scripts/deploy.sh)."""

from django.conf import settings
from django.core.checks import Error, Tags, register


@register(Tags.database, deploy=True)
def production_database(app_configs, **kwargs):
    """Production must use PostgreSQL, never a SQLite file on the server's
    disk (lost when the platform replaces the container)."""
    engine = settings.DATABASES["default"]["ENGINE"]
    if getattr(settings, "IS_PRODUCTION", False) and "sqlite" in engine:
        return [
            Error(
                "Production is using SQLite.",
                hint="Set DATABASE_URL to the PostgreSQL database.",
                id="dorm_laundry.E001",
            )
        ]
    return []
