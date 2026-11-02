"""Forms for the admin area. Labels use the plain words from docs/GLOSSARY.md."""

from django import forms
from django.core.validators import MaxValueValidator, MinValueValidator
from django.utils.translation import gettext_lazy as _

from apps.accounts.models import Resident
from apps.dorms import rules
from apps.ledger.models import LedgerEntry
from apps.payments import validators
from apps.payments.models import PaymentDetails

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


class PaymentDetailsForm(forms.Form):
    """How residents pay. A sensitive setting: the admin's password and a
    reason are required. Details are checked for typos (INN check digit,
    account number against the BIK) before residents can copy them."""

    recipient = forms.CharField(max_length=200, widget=_text())
    bank = forms.CharField(max_length=200, widget=_text())
    sbp_phone = forms.CharField(
        required=False,
        max_length=20,
        widget=_text(inputmode="tel", placeholder="+7 900 123-45-67"),
    )
    payment_link = forms.URLField(
        required=False,
        assume_scheme="https",
        widget=forms.URLInput(attrs={"class": INPUT, "placeholder": "https://"}),
        help_text=_("Only if the bank gave you a link for payments."),
    )
    qr_image = forms.FileField(
        required=False,
        widget=forms.ClearableFileInput(attrs={"class": INPUT, "accept": "image/png,image/jpeg"}),
        help_text=_("A picture of the SBP QR code, if the bank gave you one."),
    )
    remove_qr = forms.BooleanField(required=False, label=_("Remove the QR code"))
    bik = forms.CharField(required=False, max_length=20, widget=_text(inputmode="numeric"))
    account = forms.CharField(required=False, max_length=30, widget=_text(inputmode="numeric"))
    inn = forms.CharField(required=False, max_length=20, widget=_text(inputmode="numeric"))
    purpose_prefix = forms.CharField(max_length=60, widget=_text())
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

    def __init__(self, *args, user, details=None, **kwargs):
        from apps.payments.services import FIELDS, LABELS

        super().__init__(*args, **kwargs)
        self.user, self.details = user, details
        for name in (*FIELDS, "qr_image"):
            self.fields[name].label = (
                LABELS.get(name) or PaymentDetails._meta.get_field(name).verbose_name
            )
        self.fields["purpose_prefix"].help_text = PaymentDetails._meta.get_field(
            "purpose_prefix"
        ).help_text
        if details is not None:
            for name in FIELDS:
                self.initial.setdefault(name, getattr(details, name))
            self.initial["sbp_phone"] = details.sbp_phone_display if details.sbp_phone else ""
        else:
            self.initial.setdefault("purpose_prefix", "Стирка")

    def clean_password(self):
        password = self.cleaned_data["password"]
        if not self.user.check_password(password):
            raise forms.ValidationError(_("Wrong password."))
        return password

    def clean_sbp_phone(self):
        value = self.cleaned_data["sbp_phone"].strip()
        return validators.normalize_phone(value) if value else ""

    def clean_payment_link(self):
        link = self.cleaned_data["payment_link"]
        if link and not link.startswith("https://"):
            raise forms.ValidationError(_("The link must start with https://."))
        return link

    def clean_bik(self):
        bik = validators.digits(self.cleaned_data["bik"])
        if bik:
            validators.validate_bik(bik)
        return bik

    def clean_inn(self):
        inn = validators.digits(self.cleaned_data["inn"])
        if inn:
            validators.validate_inn(inn)
        return inn

    def clean_qr_image(self):
        from apps.payments.services import QrRefused, clean_qr

        upload = self.cleaned_data.get("qr_image")
        if not upload:
            return None
        try:
            return clean_qr(upload)
        except QrRefused as error:
            raise forms.ValidationError(str(error)) from None

    def clean(self):
        cleaned_data = super().clean()
        account = validators.digits(cleaned_data.get("account", ""))
        cleaned_data["account"] = account
        if account:
            bik = cleaned_data.get("bik")
            if not bik:
                self.add_error("bik", _("Enter the bank's BIK to check the account number."))
            else:
                try:
                    validators.validate_account(account, bik)
                except forms.ValidationError as error:
                    self.add_error("account", error)
        has_qr = cleaned_data.get("qr_image") or (
            self.details is not None and self.details.qr_image and not cleaned_data.get("remove_qr")
        )
        if not any(
            [cleaned_data.get("sbp_phone"), cleaned_data.get("payment_link"), has_qr, account]
        ):
            raise forms.ValidationError(
                _(
                    "Give at least one way to pay: an SBP phone number, a link, a QR code or an account."
                )
            )
        return cleaned_data


class VoidReceiptForm(forms.Form):
    reason = forms.CharField(
        label=_("Why are you voiding this receipt?"),
        max_length=500,
        widget=forms.Textarea(attrs={"class": INPUT, "rows": 3}),
        help_text=_("For example: no such payment on the bank statement. Saved in the history."),
    )
    confirm = forms.BooleanField(
        label=_("I understand: the money is taken back from the resident's balance."),
    )


class _PeriodFields(forms.Form):
    """Shared by the maintenance, extend and archive screens."""

    reason = forms.CharField(
        label=_("Reason (residents whose bookings are cancelled will see it)"),
        max_length=500,
        widget=forms.Textarea(attrs={"class": INPUT, "rows": 2}),
    )
    refund = forms.BooleanField(
        label=_("Refund affected residents in full"),
        required=False,
        initial=True,
        help_text=_("If not ticked, the usual cancellation rule decides."),
    )


LOCAL_INPUT = forms.DateTimeInput(
    attrs={"class": INPUT, "type": "datetime-local"}, format="%Y-%m-%dT%H:%M"
)


class MaintenanceForm(_PeriodFields):
    """When the machine is out of order. Times are Moscow time."""

    starts = forms.ChoiceField(
        label=_("From"),
        choices=[("now", _("Starting now")), ("later", _("Later"))],
        initial="now",
        widget=forms.RadioSelect,
    )
    starts_at = forms.DateTimeField(
        label=_("Start"), required=False, widget=LOCAL_INPUT, input_formats=["%Y-%m-%dT%H:%M"]
    )
    ends = forms.ChoiceField(
        label=_("Until"),
        choices=[("open", _("Until I end it")), ("at", _("A set time"))],
        initial="open",
        widget=forms.RadioSelect,
    )
    ends_at = forms.DateTimeField(
        label=_("End"), required=False, widget=LOCAL_INPUT, input_formats=["%Y-%m-%dT%H:%M"]
    )

    field_order = ["starts", "starts_at", "ends", "ends_at", "reason", "refund"]

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get("starts") == "later" and not cleaned_data.get("starts_at"):
            self.add_error("starts_at", _("Choose when it starts."))
        if cleaned_data.get("ends") == "at" and not cleaned_data.get("ends_at"):
            self.add_error("ends_at", _("Choose when it ends."))
        return cleaned_data

    def period(self, now):
        data = self.cleaned_data
        starts_at = now if data["starts"] == "now" else data["starts_at"]
        ends_at = data["ends_at"] if data["ends"] == "at" else None
        return starts_at, ends_at


class ExtendForm(_PeriodFields):
    ends = forms.ChoiceField(
        label=_("New end"),
        choices=[("at", _("A set time")), ("open", _("Until I end it"))],
        initial="at",
        widget=forms.RadioSelect,
    )
    ends_at = forms.DateTimeField(
        label=_("End"), required=False, widget=LOCAL_INPUT, input_formats=["%Y-%m-%dT%H:%M"]
    )

    field_order = ["ends", "ends_at", "reason", "refund"]

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get("ends") == "at" and not cleaned_data.get("ends_at"):
            self.add_error("ends_at", _("Choose when it ends."))
        return cleaned_data

    def new_end(self):
        return self.cleaned_data["ends_at"] if self.cleaned_data["ends"] == "at" else None


class ArchiveForm(_PeriodFields):
    confirm_forever = forms.BooleanField(
        label=_("I understand: the machine is removed for good and cannot come back."),
    )
