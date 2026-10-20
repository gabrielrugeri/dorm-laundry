from django.urls import path

from . import resident_import, residents, views

app_name = "manage"

urlpatterns = [
    path("", views.index, name="index"),
    path("history/", views.audit_log, name="audit"),
    path("residents/", residents.resident_list, name="residents"),
    path("residents/new/", residents.resident_add, name="resident_add"),
    path("residents/import/", resident_import.upload, name="resident_import"),
    path("residents/import/confirm/", resident_import.confirm, name="resident_import_confirm"),
    path("residents/import/done/", resident_import.done, name="resident_import_done"),
    path(
        "residents/import/login-links.csv",
        resident_import.login_links_csv,
        name="resident_import_links",
    ),
    path("residents/import/sample.csv", resident_import.sample_csv, name="resident_import_sample"),
    path("residents/<int:pk>/", residents.resident_detail, name="resident"),
    path("residents/<int:pk>/edit/", residents.resident_edit, name="resident_edit"),
    path("residents/<int:pk>/payment/", residents.resident_payment, name="resident_payment"),
    path(
        "residents/<int:pk>/correction/", residents.resident_correction, name="resident_correction"
    ),
    path(
        "residents/<int:pk>/login-link/", residents.resident_login_link, name="resident_login_link"
    ),
    path("residents/<int:pk>/reset-pin/", residents.resident_reset_pin, name="resident_reset_pin"),
    path("residents/<int:pk>/turn-off/", residents.resident_deactivate, name="resident_deactivate"),
    path("residents/<int:pk>/turn-on/", residents.resident_reactivate, name="resident_reactivate"),
    path("residents/<int:pk>/erase/", residents.resident_erase, name="resident_erase"),
    path("residents/<int:pk>/delete/", residents.resident_delete, name="resident_delete"),
    path(
        "residents/<int:pk>/history.csv",
        residents.resident_history_csv,
        name="resident_history_csv",
    ),
    path(
        "residents/<int:pk>/bookings/<uuid:group_id>/cancel/",
        residents.resident_cancel_booking,
        name="resident_cancel_booking",
    ),
]
