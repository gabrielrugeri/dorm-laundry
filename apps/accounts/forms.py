from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from . import ratelimit
from .validators import validate_pin

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


def _pin_input():
    return forms.PasswordInput(
        attrs={
            "autocomplete": "new-password",
            "inputmode": "numeric",
            "maxlength": "6",
            "class": INPUT_CLASS,
        }
    )


class SetPinForm(forms.Form):
    """Choose a PIN (first activation or after a reset by the admin).

    Takes the user as first argument, like Django's SetPasswordForm, so it
    works with PasswordResetConfirmView. Staff password rules do not apply.
    """

    pin1 = forms.CharField(
        label=_("New PIN"),
        strip=False,
        widget=_pin_input(),
        help_text=_("6 digits. Avoid repeated or consecutive digits."),
    )
    pin2 = forms.CharField(label=_("Repeat the PIN"), strip=False, widget=_pin_input())

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_pin1(self):
        pin = self.cleaned_data["pin1"]
        validate_pin(pin)
        return pin

    def clean(self):
        cleaned_data = super().clean()
        pin1, pin2 = cleaned_data.get("pin1"), cleaned_data.get("pin2")
        if pin1 and pin2 and pin1 != pin2:
            self.add_error("pin2", _("The two PINs do not match."))
        return cleaned_data

    def save(self):
        self.user.set_password(self.cleaned_data["pin1"])
        self.user.save(update_fields=["password"])
        return self.user
