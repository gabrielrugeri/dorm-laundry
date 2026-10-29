from django.conf import settings
from django.contrib.auth import views as auth_views
from django.http import HttpResponseRedirect
from django.urls import reverse_lazy
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext_lazy as _
from django.views import i18n
from django.views.decorators.http import require_POST

from .forms import LoginForm, SetPinForm
from .models import UserPreferences


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


@require_POST
def set_language(request):
    """Django's language switch, plus: a logged-in resident's choice is saved
    on their profile, so the next login on any device uses it."""
    response = i18n.set_language(request)
    code = request.POST.get("language")
    resident = getattr(request.user, "resident", None) if request.user.is_authenticated else None
    if (
        resident is not None
        and not resident.is_anonymized
        and code in dict(settings.LANGUAGES)
        and resident.language != code
    ):
        resident.language = code
        resident.save(update_fields=["language"])
    return response


THEME_COOKIE = "theme"


@require_POST
def set_theme(request):
    """Light, dark or like the phone. Kept in a cookie (also before logging
    in) and, for a logged-in user, saved for all their devices."""
    theme = request.POST.get("theme")
    if theme not in UserPreferences.Theme.values:
        theme = UserPreferences.Theme.SYSTEM
    if request.user.is_authenticated:
        UserPreferences.objects.update_or_create(user=request.user, defaults={"theme": theme})
    next_url = request.POST.get("next", "/")
    if not url_has_allowed_host_and_scheme(
        next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        next_url = "/"
    response = HttpResponseRedirect(next_url)
    response.set_cookie(
        THEME_COOKIE,
        theme,
        max_age=60 * 60 * 24 * 365,
        samesite="Lax",
        secure=request.is_secure(),
    )
    return response


class LoginView(auth_views.LoginView):
    form_class = LoginForm
    template_name = "accounts/login.html"
    redirect_authenticated_user = True

    def form_valid(self, form):
        return remember_language(super().form_valid(form), form.get_user())


class ActivateView(auth_views.PasswordResetConfirmView):
    """The page behind an activation link: the resident chooses a PIN and is
    logged in. Django's view moves the token out of the URL into the session
    before showing the form, so it does not leak through the Referer header."""

    form_class = SetPinForm
    template_name = "accounts/activate.html"
    title = _("Choose your PIN")
    reset_url_token = "set-pin"
    post_reset_login = True
    post_reset_login_backend = "apps.accounts.backends.ResidentBackend"
    success_url = reverse_lazy("core:home")

    def get_user(self, uidb64):
        user = super().get_user(uidb64)
        # Activation links are for residents only.
        if user is not None and getattr(user, "resident", None) is None:
            return None
        return user

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if not context["validlink"]:
            # Django's default title here talks about password resets.
            context["title"] = _("Link not valid")
        return context

    def form_valid(self, form):
        return remember_language(super().form_valid(form), self.user)
