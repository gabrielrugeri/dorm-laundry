from django.urls import path

from . import views

app_name = "ledger"

urlpatterns = [
    path("balance/", views.balance, name="balance"),
]
