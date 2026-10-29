"""Forms for the admin area. Labels use the plain words from docs/GLOSSARY.md."""

from django import forms
from django.utils.translation import gettext_lazy as _

from apps.accounts.models import Resident
from apps.ledger.models import LedgerEntry

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


class ChangeBalanceForm(forms.Form):
    """One screen for every manual money change. A payment and a correction
    are stored as different kinds, so reconciliation keeps them apart."""

    PAYMENT, CORRECTION = "payment", "correction"
    ADD, SUBTRACT = "add", "subtract"

    type = forms.ChoiceField(
        label=_("What happened"),
        choices=[(PAYMENT, _("Payment received")), (CORRECTION, _("Correction"))],
        initial=PAYMENT,
        widget=forms.RadioSelect,
    )
    direction = forms.ChoiceField(
        label=_("Balance"),
        choices=[(ADD, _("Add")), (SUBTRACT, _("Subtract"))],
        initial=ADD,
        widget=forms.RadioSelect,
    )
    amount = forms.IntegerField(
        label=_("Amount, ₽"),
        min_value=1,
        widget=forms.NumberInput(
            attrs={"class": INPUT, "inputmode": "numeric", "data-balance-amount": ""}
        ),
    )
    note = forms.CharField(
        label=_("Comment"),
        required=False,
        max_length=500,
        widget=_text(placeholder=_("For example: cash, 15 October")),
        help_text=_("Required for a correction. Saved in the resident's payment history."),
    )

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get("type") == self.CORRECTION and not cleaned_data.get("note", "").strip():
            self.add_error("note", _("Explain the correction."))
        return cleaned_data

    @property
    def kind(self):
        if self.cleaned_data["type"] == self.PAYMENT:
            return LedgerEntry.Kind.CREDIT
        return LedgerEntry.Kind.ADJUSTMENT

    @property
    def signed_amount(self):
        amount = self.cleaned_data["amount"]
        return -amount if self.cleaned_data["direction"] == self.SUBTRACT else amount


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
