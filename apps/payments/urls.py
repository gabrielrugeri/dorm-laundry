from django.urls import path

from . import views

app_name = "payments"

urlpatterns = [
    path("how-to-pay/", views.how_to_pay, name="how_to_pay"),
    path("how-to-pay/qr.png", views.qr_image, name="qr"),
]
