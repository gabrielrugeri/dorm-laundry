"""Forms for the admin area. Labels use the plain words from docs/GLOSSARY.md."""

from django import forms
from django.core.validators import MaxValueValidator, MinValueValidator
from django.utils.translation import gettext_lazy as _

from apps.accounts.models import Resident
from apps.dorms import rules
from apps.ledger.models import LedgerEntry

INPUT = "w-full rounded border border-line-strong bg-surface px-3 py-2"


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


class RulesForm(forms.Form):
    """Change the money and upload rules: a sensitive setting. Needs the
    admin's own password and a reason; big jumps need an extra tick."""

    credit_limit = forms.IntegerField(
        required=False,
        widget=forms.NumberInput(attrs={"class": INPUT, "inputmode": "numeric"}),
        help_text=_("In rubles. 0: residents cannot go into debt. Empty: no limit."),
    )
    max_receipt_amount = forms.IntegerField(
        widget=forms.NumberInput(attrs={"class": INPUT, "inputmode": "numeric"}),
        help_text=_("In rubles."),
    )
    max_credit_per_30_days = forms.IntegerField(
        widget=forms.NumberInput(attrs={"class": INPUT, "inputmode": "numeric"}),
        help_text=_("In rubles, counted over the last 30 days."),
    )
    max_uploads_per_day = forms.IntegerField(
        widget=forms.NumberInput(attrs={"class": INPUT, "inputmode": "numeric"}),
    )
    max_upload_mb = forms.IntegerField(
        widget=forms.NumberInput(attrs={"class": INPUT, "inputmode": "numeric"}),
    )
    reason = forms.CharField(
        label=_("Why are you changing this?"),
        max_length=500,
        widget=_text(),
        help_text=_("Saved in the change history."),
    )
    password = forms.CharField(
        label=_("Your password"),
        strip=False,
        widget=forms.PasswordInput(attrs={"class": INPUT, "autocomplete": "current-password"}),
        help_text=_("To make sure it is really you."),
    )
    confirm_big = forms.BooleanField(required=False)

    def __init__(self, *args, user, current, **kwargs):
        super().__init__(*args, **kwargs)
        self.user, self.current = user, current
        for name in rules.FIELDS:
            low, high = rules.bounds()[name]
            field = self.fields[name]
            field.label = rules.LABELS[name]
            field.min_value, field.max_value = low, high
            field.validators += [MinValueValidator(low), MaxValueValidator(high)]
            field.widget.attrs.update(min=low, max=high)
            self.initial.setdefault(name, getattr(current, name))
        self.big = []

    def clean_password(self):
        password = self.cleaned_data["password"]
        if not self.user.check_password(password):
            raise forms.ValidationError(_("Wrong password."))
        return password

    def clean(self):
        cleaned_data = super().clean()
        if any(name not in cleaned_data for name in rules.FIELDS):
            return cleaned_data
        values = self.values()
        if all(values[name] == getattr(self.current, name) for name in rules.FIELDS):
            raise forms.ValidationError(_("Nothing was changed."))
        if values["max_credit_per_30_days"] < values["max_receipt_amount"]:
            self.add_error(
                "max_credit_per_30_days",
                _("Cannot be less than the largest amount on one receipt."),
            )
        self.big = rules.big_changes(self.current, values)
        if self.big and not cleaned_data.get("confirm_big"):
            raise forms.ValidationError(
                _("Some values change a lot. Check them, tick the box and save again."),
                code="confirm_big",
            )
        return cleaned_data

    def values(self):
        return {name: self.cleaned_data[name] for name in rules.FIELDS}
