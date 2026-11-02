from django import forms
from django.utils.translation import gettext_lazy as _

INPUT = "w-full rounded border border-line-strong bg-surface px-3 py-2"


class ReceiptForm(forms.Form):
    amount = forms.IntegerField(
        label=_("Amount on the receipt, ₽"),
        min_value=1,
        widget=forms.NumberInput(attrs={"class": INPUT, "inputmode": "numeric"}),
        help_text=_("Whole rubles, exactly as on the receipt."),
    )
    file = forms.FileField(
        label=_("Receipt"),
        widget=forms.ClearableFileInput(
            attrs={"class": INPUT, "accept": "application/pdf,image/jpeg,image/png,image/webp"}
        ),
        help_text=_("A screenshot or a PDF from your bank app."),
    )

    def __init__(self, *args, max_amount, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["amount"].max_value = max_amount
        self.fields["amount"].widget.attrs["max"] = max_amount
