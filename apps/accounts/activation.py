"""One-time activation links that let a resident choose their PIN.

They are Django password-reset tokens: no extra table, valid for
PASSWORD_RESET_TIMEOUT, and invalid as soon as the PIN changes (the token is
tied to the password hash). The admin hands the link to the resident.
"""

from django.contrib.auth.tokens import default_token_generator
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode


def activation_url(request, user):
    path = reverse(
        "accounts:activate",
        kwargs={
            "uidb64": urlsafe_base64_encode(force_bytes(user.pk)),
            "token": default_token_generator.make_token(user),
        },
    )
    return request.build_absolute_uri(path)
