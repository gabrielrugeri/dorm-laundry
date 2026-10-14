from django.conf import settings
from django.contrib.auth import views as auth_views

from .forms import LoginForm


def remember_language(response, user):
    """Switch the interface to the resident's saved language (a cookie, like
    the language switch uses)."""
    resident = getattr(user, "resident", None)
    if resident is not None:
        response.set_cookie(
            settings.LANGUAGE_COOKIE_NAME,
            resident.language,
            max_age=settings.LANGUAGE_COOKIE_AGE,
            samesite=settings.LANGUAGE_COOKIE_SAMESITE,
            secure=settings.LANGUAGE_COOKIE_SECURE,
        )
    return response


class LoginView(auth_views.LoginView):
    form_class = LoginForm
    template_name = "accounts/login.html"
    redirect_authenticated_user = True

    def form_valid(self, form):
        return remember_language(super().form_valid(form), form.get_user())
