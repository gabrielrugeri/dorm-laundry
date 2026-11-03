from django import forms
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from . import initial_pins, pins, ratelimit
from .validators import validate_pin

# Tailwind classes shared by the text inputs of our forms.
INPUT_CLASS = "w-full rounded border border-line-strong bg-surface px-3 py-2"


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
        "wait": _("Too many attempts from your network. Wait %(seconds)s s and try again."),
    }

    def clean(self):
        code = self.cleaned_data.get("username") or ""
        if code:
            refused_because(code, self.request, self.error_messages)
        try:
            cleaned_data = super().clean()
        except ValidationError:
            if code:
                ratelimit.register_failure(code, self.request)
            raise
        ratelimit.reset(code, self.request)
        return cleaned_data


def refused_because(code, request, messages):
    """Raise the plain-language ValidationError for a refused attempt
    (apps/accounts/ratelimit.py), or do nothing."""
    refusal = ratelimit.check(code, request)
    if refusal is None:
        return
    if refusal.reason == ratelimit.Refusal.ADDRESS_WAIT:
        raise ValidationError(messages["wait"], code="wait", params={"seconds": refusal.seconds})
    raise ValidationError(messages["locked"], code="locked")


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
        pins.set_pin(self.user, self.cleaned_data["pin1"])
        self.user.save(update_fields=["password"])
        resident = getattr(self.user, "resident", None)
        if resident is not None:
            initial_pins.clear(resident)  # their own PIN replaces a first-time one
        return self.user


class ChangePinForm(SetPinForm):
    """A logged-in resident changes their PIN: the current one, then the new
    one twice. A wrong current PIN counts toward the login limits, so this
    page cannot be used to guess PINs either."""

    error_messages = LoginForm.error_messages

    current = forms.CharField(
        label=_("Current PIN"),
        strip=False,
        widget=forms.PasswordInput(
            attrs={
                "autocomplete": "current-password",
                "inputmode": "numeric",
                "maxlength": "6",
                "class": INPUT_CLASS,
            }
        ),
    )
    field_order = ["current", "pin1", "pin2"]

    def __init__(self, user, *args, request=None, **kwargs):
        self.request = request
        super().__init__(user, *args, **kwargs)
        if user.resident.must_change_pin:
            self.fields["current"].label = _("The PIN you logged in with (date of birth)")

    def clean_current(self):
        current = self.cleaned_data["current"]
        code = self.user.resident.student_code
        refused_because(code, self.request, self.error_messages)
        if not pins.check_pin(self.user, current):
            ratelimit.register_failure(code, self.request)
            raise ValidationError(_("This is not your current PIN."), code="wrong_pin")
        return current

    def clean(self):
        cleaned_data = super().clean()
        current, new = cleaned_data.get("current"), cleaned_data.get("pin1")
        if current and new and current == new:
            self.add_error("pin1", _("The new PIN must be different from the current one."))
        return cleaned_data


class ChangePasswordForm(PasswordChangeForm):
    """Staff change their password. A wrong current password counts toward
    the login limits, like a wrong one on the login page."""

    error_messages = {**PasswordChangeForm.error_messages, **LoginForm.error_messages}

    def __init__(self, user, *args, request=None, **kwargs):
        self.request = request
        super().__init__(user, *args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = INPUT_CLASS

    def clean_old_password(self):
        refused_because(self.user.get_username(), self.request, self.error_messages)
        try:
            return super().clean_old_password()
        except ValidationError:
            ratelimit.register_failure(self.user.get_username(), self.request)
            raise
