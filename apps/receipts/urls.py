from django.urls import path

from . import views

app_name = "receipts"

urlpatterns = [
    path("balance/receipt/", views.new, name="new"),
    path("receipts/<int:pk>/file/", views.file, name="file"),
]
