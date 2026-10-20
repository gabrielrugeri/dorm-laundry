from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class ManageConfig(AppConfig):
    name = "apps.manage"
    verbose_name = _("Management")
