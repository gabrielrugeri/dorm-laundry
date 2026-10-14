from django.urls import path, register_converter

from . import converters, views

register_converter(converters.IsoDateConverter, "isodate")

app_name = "bookings"

urlpatterns = [
    path("book/<isodate:day>/<int:slot_id>/", views.book, name="book"),
    path("bookings/", views.my_bookings, name="mine"),
    path("bookings/confirmed/", views.confirmed, name="confirmed"),
    path("bookings/<uuid:group_id>/", views.group_detail, name="detail"),
    path("bookings/<uuid:group_id>/cancel/", views.cancel, name="cancel"),
    path("bookings/<uuid:group_id>/calendar.ics", views.calendar_file, name="calendar"),
]
