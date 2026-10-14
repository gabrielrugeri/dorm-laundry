from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class KeylogConfig(AppConfig):
    name = "apps.keylog"
    verbose_name = _("Key log")
