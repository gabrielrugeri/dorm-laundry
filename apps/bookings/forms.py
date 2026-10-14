from django import forms
from django.utils.translation import gettext_lazy as _


class BookingForm(forms.Form):
    """Tick one or more machines to book for the chosen slots.

    `choices` are availability.MachineChoice items for every machine. Only the
    available ones are valid choices, so an unavailable machine cannot be
    submitted even by editing the page.
    """

    machines = forms.MultipleChoiceField(
        label=_("Machines"),
        widget=forms.CheckboxSelectMultiple,
        error_messages={"required": _("Choose at least one machine.")},
    )

    def __init__(self, choices, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.choices = choices
        self.available = {str(c.machine.pk): c.machine for c in choices if c.available}
        self.fields["machines"].choices = [(pk, m.name) for pk, m in self.available.items()]

    def selected(self):
        """Machine pks ticked in the submitted data (to keep them ticked)."""
        return set(self.data.getlist("machines")) if self.is_bound else set()

    def clean_machines(self):
        return [self.available[pk] for pk in self.cleaned_data["machines"]]
