from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class ReceiptsConfig(AppConfig):
    name = "apps.receipts"
    verbose_name = _("Receipts")
