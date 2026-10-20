from django.contrib.admin.apps import AdminConfig


class SuperuserAdminConfig(AdminConfig):
    """Replaces 'django.contrib.admin' in INSTALLED_APPS: Django admin for
    superusers only (see apps/core/admin_site.py)."""

    default_site = "apps.core.admin_site.SuperuserAdminSite"
