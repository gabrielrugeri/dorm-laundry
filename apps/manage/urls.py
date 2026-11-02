from django.urls import path

from . import (
    dashboard_views,
    machine_views,
    payment_views,
    receipt_views,
    resident_import,
    residents,
    settings_views,
    views,
)

app_name = "manage"

urlpatterns = [
    path("", views.index, name="index"),
    path("overview/", dashboard_views.dashboard, name="dashboard"),
    path("machines/", machine_views.machine_list, name="machines"),
    path(
        "machines/<int:pk>/maintenance/",
        machine_views.machine_maintenance,
        name="machine_maintenance",
    ),
    path("machines/<int:pk>/archive/", machine_views.machine_archive, name="machine_archive"),
    path("machines/periods/<int:pk>/extend/", machine_views.period_extend, name="period_extend"),
    path("machines/periods/<int:pk>/end/", machine_views.period_end, name="period_end"),
    path("history/", views.audit_log, name="audit"),
    path("receipts/", receipt_views.receipt_list, name="receipts"),
    path("receipts/report/", receipt_views.receipt_report, name="receipt_report"),
    path("receipts/<int:pk>/", receipt_views.receipt_detail, name="receipt"),
    path("receipts/<int:pk>/void/", receipt_views.receipt_void, name="receipt_void"),
    path("settings/", settings_views.settings_page, name="settings"),
    path("settings/change/", settings_views.settings_change, name="settings_change"),
    path("settings/payments/", payment_views.payment_details_edit, name="payment_details"),
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
    path("residents/<int:pk>/balance/", residents.resident_balance, name="resident_balance"),
    path(
        "residents/<int:pk>/login-link/", residents.resident_login_link, name="resident_login_link"
    ),
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
