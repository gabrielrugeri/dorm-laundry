from django import forms
from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext


class BookingForm(forms.Form):
    """Pick a machine and how many consecutive slots to book.

    `runs` is [(machine, count), ...] from availability.free_runs(): each free
    machine and how many slots in a row it stays free. `slots` are the slots
    that can follow the chosen one.
    """

    machine = forms.ChoiceField(label=_("Machine"), widget=forms.RadioSelect)
    count = forms.TypedChoiceField(label=_("How long"), coerce=int, widget=forms.RadioSelect)

    def __init__(self, runs, slots, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.runs = {str(machine.pk): (machine, count) for machine, count in runs}
        self.fields["machine"].choices = [
            (str(machine.pk), machine.name) for machine, _count in runs
        ]
        longest = max((count for _machine, count in runs), default=0)
        self.fields["count"].choices = [
            (n, self._duration_label(slots, n)) for n in range(1, longest + 1)
        ]
        self.fields["count"].initial = 1
        if len(runs) == 1:
            self.fields["machine"].initial = str(runs[0][0].pk)

    @staticmethod
    def _duration_label(slots, n):
        span = f"{slots[0].start_time:%H:%M}–{slots[n - 1].end_time:%H:%M}"
        return ngettext("%(n)s slot (%(span)s)", "%(n)s slots (%(span)s)", n) % {
            "n": n,
            "span": span,
        }

    def clean(self):
        cleaned_data = super().clean()
        choice, count = cleaned_data.get("machine"), cleaned_data.get("count")
        if choice and count:
            machine, free = self.runs[choice]
            if count > free:
                self.add_error(
                    "count",
                    ngettext(
                        "%(machine)s is free for only %(free)s slot from this time.",
                        "%(machine)s is free for only %(free)s slots from this time.",
                        free,
                    )
                    % {"machine": machine.name, "free": free},
                )
            cleaned_data["machine"] = machine
        return cleaned_data
