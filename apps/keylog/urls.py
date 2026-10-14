from django.urls import path

from . import views

app_name = "keylog"

urlpatterns = [
    path("staff/keys/<uuid:group_id>/<slug:action>/", views.key_action, name="action"),
]
