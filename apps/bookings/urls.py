from django.urls import path, register_converter

from . import converters, views

register_converter(converters.IsoDateConverter, "isodate")

app_name = "bookings"

urlpatterns = [
    path("book/<isodate:day>/<int:slot_id>/", views.book, name="book"),
    path("bookings/<uuid:group_id>/", views.group_detail, name="detail"),
]
