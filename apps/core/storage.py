"""Storage for files only our own views may hand out (receipts, QR codes).

They live in PRIVATE_MEDIA_ROOT, outside the static files and outside any
public URL: there is no MEDIA_URL. A view checks who is asking and then sends
the file (see apps/receipts/views.py).
"""

import os

from django.conf import settings
from django.core.files.storage import FileSystemStorage


class PrivateStorage(FileSystemStorage):
    @property
    def base_location(self):
        return settings.PRIVATE_MEDIA_ROOT

    @property
    def location(self):
        return os.path.abspath(self.base_location)

    def url(self, name):
        raise ValueError("Private files have no public URL; serve them through a view.")


private_storage = PrivateStorage()
