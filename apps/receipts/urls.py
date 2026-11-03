from django.urls import path

from . import views

app_name = "receipts"

urlpatterns = [
    path("balance/receipt/", views.new, name="new"),
    path("receipts/<int:pk>/", views.view, name="view"),
    path("receipts/<int:pk>/inline/", views.inline, name="inline"),
    path("receipts/<int:pk>/file/", views.file, name="file"),
]
