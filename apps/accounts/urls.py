from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("login/", views.LoginView.as_view(), name="login"),
    # Django's LogoutView accepts POST only, so a link cannot log users out.
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("language/", views.set_language, name="set_language"),
    path("activate/<uidb64>/<token>/", views.ActivateView.as_view(), name="activate"),
]
