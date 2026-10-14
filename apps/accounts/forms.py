from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from . import ratelimit

# Tailwind classes shared by the text inputs of our forms.
INPUT_CLASS = "w-full rounded border border-slate-300 bg-white px-3 py-2"


class LoginForm(AuthenticationForm):
    """Student code + PIN (staff type their username and password here).

    Every failure shows the same message, whether the code is unknown, the
    PIN is wrong or the account is inactive, so the form cannot be used to
    find out which student codes exist.
    """

    username = forms.CharField(
        label=_("Student code"),
        widget=forms.TextInput(
            attrs={"autofocus": True, "autocomplete": "username", "class": INPUT_CLASS}
        ),
    )
    password = forms.CharField(
        label=_("PIN"),
        strip=False,
        widget=forms.PasswordInput(
            attrs={
                "autocomplete": "current-password",
                "inputmode": "numeric",
                "class": INPUT_CLASS,
            }
        ),
    )

    error_messages = {
        "invalid_login": _("Invalid student code or PIN."),
        "inactive": _("Invalid student code or PIN."),
        "locked": _("Too many failed attempts. Please try again later."),
    }

    def clean(self):
        code = self.cleaned_data.get("username") or ""
        if code and ratelimit.is_locked(code, self.request):
            raise ValidationError(self.error_messages["locked"], code="locked")
        try:
            cleaned_data = super().clean()
        except ValidationError:
            if code:
                ratelimit.register_failure(code, self.request)
            raise
        ratelimit.reset(code, self.request)
        return cleaned_data
