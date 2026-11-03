from django.conf import settings
from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth import views as auth_views
from django.db import transaction
from django.http import HttpResponseRedirect
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext_lazy as _
from django.views import i18n
from django.views.decorators.http import require_POST

from apps.audit.services import record

from . import ratelimit
from .decorators import is_staff_member, resident_required, staff_required
from .forms import (
    ChangePasswordForm,
    ChangePinForm,
    LoginForm,
    SetPinForm,
    StaffSetPasswordForm,
)
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
        user = form.get_user()
        resident = getattr(user, "resident", None)
        if resident is not None and resident.must_change_pin:
            record(actor=user, action="resident.initial_pin_login", target=resident)
        return remember_language(super().form_valid(form), user)


class StaffSetPasswordView(auth_views.PasswordResetConfirmView):
    """The page behind a staff password link (`manage.py dormitory_admin`):
    a dormitory admin or manager chooses their password, then logs in.
    Links for residents or switched-off accounts do not work here."""

    form_class = StaffSetPasswordForm
    template_name = "accounts/set_password.html"
    title = _("Choose your password")
    reset_url_token = "set-password"
    success_url = reverse_lazy("accounts:login")

    def get_user(self, uidb64):
        user = super().get_user(uidb64)
        if user is not None and (not user.is_active or not is_staff_member(user)):
            return None
        return user

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if not context["validlink"]:
            context["title"] = _("Link not valid")
        return context

    def form_valid(self, form):
        with transaction.atomic():
            response = super().form_valid(form)
            record(actor=self.user, action="user.password_set_by_link", target=self.user)
        messages.success(self.request, _("Password saved. Log in with your username and it."))
        return response


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


@resident_required
def change_pin(request):
    """The resident changes their own PIN. Every other device they are
    logged in on is logged out; this one stays logged in."""
    resident = request.user.resident
    forced = resident.must_change_pin
    form = ChangePinForm(request.user, request.POST or None, request=request)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            form.save()
            action = "resident.initial_pin_changed" if forced else "resident.pin_change"
            record(actor=request.user, action=action, target=resident)
        ratelimit.reset(request.user.resident.student_code, request)
        update_session_auth_hash(request, request.user)
        messages.success(request, _("Your PIN was changed. Other devices were logged out."))
        return redirect("core:home")
    return render(request, "accounts/change_pin.html", {"form": form, "forced": forced})


class ChangePasswordView(auth_views.PasswordChangeView):
    """Staff change their own password (Django keeps this session logged in
    and logs out the others)."""

    form_class = ChangePasswordForm
    template_name = "accounts/change_password.html"
    success_url = reverse_lazy("core:home")

    def get_form_kwargs(self):
        return {**super().get_form_kwargs(), "request": self.request}

    def form_valid(self, form):
        with transaction.atomic():
            response = super().form_valid(form)
            record(actor=self.request.user, action="user.password_change", target=self.request.user)
        ratelimit.reset(self.request.user.get_username(), self.request)
        messages.success(
            self.request, _("Your password was changed. Other devices were logged out.")
        )
        return response


change_password = staff_required(ChangePasswordView.as_view())
