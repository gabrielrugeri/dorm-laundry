"""Forms for the admin area. Labels use the plain words from docs/GLOSSARY.md."""

from django import forms
from django.utils.translation import gettext_lazy as _

from apps.accounts.models import Resident

INPUT = "w-full rounded border border-slate-300 bg-white px-3 py-2"


def _text(**attrs):
    return forms.TextInput(attrs={"class": INPUT, **attrs})


class ResidentForm(forms.Form):
    full_name = forms.CharField(label=_("Full name"), max_length=200, widget=_text())
    room = forms.CharField(label=_("Room"), max_length=20, widget=_text())
    student_code = forms.CharField(
        label=_("Student code"),
        max_length=32,
        widget=_text(autocapitalize="characters"),
        help_text=_("The resident logs in with this code."),
    )

    def __init__(self, *args, dormitory, resident=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.dormitory, self.resident = dormitory, resident

    def clean_student_code(self):
        code = self.cleaned_data["student_code"].strip()
        others = Resident.objects.filter(dormitory=self.dormitory, student_code__iexact=code)
        if self.resident is not None:
            others = others.exclude(pk=self.resident.pk)
        if others.exists():
            raise forms.ValidationError(_("Another resident already has this student code."))
        return code


class PaymentForm(forms.Form):
    """Money the resident paid (e.g. cash at the desk): increases the balance."""

    amount = forms.IntegerField(
        label=_("Amount, ₽"),
        min_value=1,
        widget=forms.NumberInput(attrs={"class": INPUT, "inputmode": "numeric"}),
    )
    note = forms.CharField(
        label=_("Comment"),
        max_length=500,
        widget=_text(placeholder=_("For example: cash, 15 October")),
        help_text=_("Required. Saved in the resident's payment history."),
    )


class CorrectionForm(forms.Form):
    """Fix a mistake: positive adds money, negative takes it away."""

    amount = forms.IntegerField(
        label=_("Change, ₽"),
        widget=forms.NumberInput(attrs={"class": INPUT, "inputmode": "numeric"}),
        help_text=_("Use a minus sign to reduce the balance, e.g. -50."),
    )
    note = forms.CharField(
        label=_("Why"),
        max_length=500,
        widget=_text(),
        help_text=_("Required. Explain the correction."),
    )

    def clean_amount(self):
        amount = self.cleaned_data["amount"]
        if amount == 0:
            raise forms.ValidationError(_("The change cannot be zero."))
        return amount


class CancelBookingForm(forms.Form):
    reason = forms.CharField(
        label=_("Reason (the resident will see it)"),
        max_length=500,
        widget=forms.Textarea(attrs={"class": INPUT, "rows": 3}),
    )
    refund = forms.ChoiceField(
        label=_("Money"),
        choices=[
            ("rule", _("Usual rule (refund only if early enough)")),
            ("full", _("Full refund")),
        ],
        initial="rule",
        widget=forms.RadioSelect,
    )


class ConfirmDebtForm(forms.Form):
    """Shown only when the resident owes money."""

    confirm_debt = forms.BooleanField(
        label=_("I have seen that this resident owes money."), required=True
    )
