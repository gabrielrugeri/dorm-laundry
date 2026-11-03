"""The printable poster for residents (/manage/poster/) and the help text it
shows, which admins edit under «Настройки».

The poster is one A4 page in Russian or English: a QR code to the app, how
to install it on iPhone and Android, how to log in the first time (student
code and date of birth as DDMMYY), and where to get help. The QR code is an
SVG made on our server (segno): nothing is loaded from elsewhere.
"""

import segno
from django import forms
from django.conf import settings
from django.contrib import messages
from django.db import transaction
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import translation
from django.utils.safestring import mark_safe
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from apps.audit.services import record, snapshot
from apps.dorms import rules

from .forms import INPUT
from .views import admin_required


class HelpContactForm(forms.Form):
    help_contact = forms.CharField(
        label=gettext_lazy("Where residents get help"),
        required=False,
        max_length=300,
        widget=forms.Textarea(attrs={"class": INPUT, "rows": 3}),
        help_text=gettext_lazy(
            "Printed on the poster, e.g. room 105, Mon–Fri 18:00–20:00, or a phone number."
        ),
    )


@admin_required
def help_contact_edit(request):
    """Not a sensitive setting: no password or reason, but in the history."""
    dormitory = request.dormitory
    form = HelpContactForm(request.POST or None, initial={"help_contact": dormitory.help_contact})
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            before = snapshot(dormitory)
            dormitory.help_contact = form.cleaned_data["help_contact"].strip()
            dormitory.save(update_fields=["help_contact"])
            record(
                actor=request.user,
                action="dormitory.help_contact",
                target=dormitory,
                before=before,
                after=snapshot(dormitory),
            )
        messages.success(request, _("Saved. It is on the poster now."))
        return redirect("manage:settings")
    return render(request, "manage/help_contact.html", {"form": form})


def qr_svg(url):
    """The QR code as inline SVG: black on white, sized by CSS."""
    return mark_safe(
        segno.make(url, error="m").svg_inline(omitsize=True, dark="#000", light="#fff")
    )  # noqa: S308  (made by segno from our own URL)


@admin_required
def poster(request):
    language = request.GET.get("lang", "")
    if language not in dict(settings.LANGUAGES):
        language = translation.get_language()
    app_url = request.build_absolute_uri(reverse("core:home"))
    context = {
        "dormitory": request.dormitory,
        "app_url": app_url,
        "qr": qr_svg(app_url),
        "initial_pin_days": rules.current().initial_pin_days,
        "poster_language": language,
    }
    with translation.override(language):
        response = render(request, "manage/poster.html", context)
    return response
