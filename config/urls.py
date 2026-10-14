from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("i18n/", include("django.conf.urls.i18n")),
    path("account/", include("apps.accounts.urls")),
    path("", include("apps.bookings.urls")),
    path("", include("apps.ledger.urls")),
    path("", include("apps.keylog.urls")),
    path("", include("apps.core.urls")),
]
