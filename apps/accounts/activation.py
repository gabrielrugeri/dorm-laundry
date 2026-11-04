"""One-time activation links that let a resident choose their PIN.

They are Django password-reset tokens: no extra table, valid for
PASSWORD_RESET_TIMEOUT, and invalid as soon as the PIN changes (the token is
tied to the password hash). The admin hands the link to the resident.
"""

from django.contrib.auth.tokens import default_token_generator
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode


def _path(name, user):
    return reverse(
        name,
        kwargs={
            "uidb64": urlsafe_base64_encode(force_bytes(user.pk)),
            "token": default_token_generator.make_token(user),
        },
    )


def activation_url(request, user):
    return request.build_absolute_uri(_path("accounts:activate", user))


def staff_password_url(base_url, user):
    """A one-time link where a dormitory admin or manager sets their password
    (made by `manage.py dormitory_admin`, which has no request). Valid for
    PASSWORD_RESET_TIMEOUT and only until the password is set."""
    return base_url.rstrip("/") + _path("accounts:set_password", user)
