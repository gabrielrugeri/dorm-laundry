"""The resident's history as display lines.

The ledger keeps one entry per slot, so partial cancellations and refunds stay
exact. Residents think in bookings, so entries next to each other in time with
the same booking group and kind (e.g. the two charges of a 4-hour booking) are
shown as one line, with the per-slot entries as a detail. Nothing is stored
differently; this is display only.
"""

from dataclasses import dataclass, field


@dataclass
class Line:
    entries: list = field(default_factory=list)  # newest first, like the page

    @property
    def first(self):
        return self.entries[0]

    @property
    def kind_label(self):
        return self.first.get_kind_display()

    @property
    def created_at(self):
        return self.first.created_at

    @property
    def amount(self):
        return sum(entry.amount for entry in self.entries)

    @property
    def bookings(self):
        return sorted((e.booking for e in self.entries if e.booking), key=lambda b: b.starts_at)

    @property
    def machine(self):
        return self.bookings[0].machine if self.bookings else None

    @property
    def starts_at(self):
        return self.bookings[0].starts_at if self.bookings else None

    @property
    def ends_at(self):
        return self.bookings[-1].ends_at if self.bookings else None

    @property
    def note(self):
        return "" if self.bookings else self.first.note

    @property
    def is_grouped(self):
        return len(self.entries) > 1


def _key(entry):
    """Entries with the same key next to each other become one line."""
    if entry.booking_id is None:
        return None  # payments and corrections always stand alone
    return (entry.booking.group_id, entry.kind)


def display_lines(entries):
    lines = []
    for entry in entries:
        key = _key(entry)
        if lines and key is not None and _key(lines[-1].first) == key:
            lines[-1].entries.append(entry)
        else:
            lines.append(Line([entry]))
    return lines
