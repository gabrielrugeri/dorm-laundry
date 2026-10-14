from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class DormsConfig(AppConfig):
    name = "apps.dorms"
    verbose_name = _("Dormitories")
