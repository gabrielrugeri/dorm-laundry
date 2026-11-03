"""Importing residents from a CSV file (student code, name, room; optionally
date of birth and opening balance).

Two steps, so nothing is written until the admin has seen what will happen:

1. `preview(dormitory, data)` reads the file and compares every row with the
   residents already in the dormitory: new, changed (with before/after per
   field), unchanged, or error (with the reason). It writes nothing.
2. `apply(actor, dormitory, rows=stored(preview))` applies what was
   previewed, in one transaction, through the services (one audit event per
   change). Rows with errors are skipped. Between the two steps only
   `stored(preview)` is kept (in the admin's session): codes, names, rooms,
   opening balances and the hashed first-time PINs, never the file and never
   a date of birth.

Optional columns:
- Date of birth: gives a new resident a first-time PIN (DDMMYY,
  apps/accounts/initial_pins.py). Parsed strictly; the date is thrown away
  as soon as the PIN's hash is made. Residents who have not chosen their own
  PIN yet get a new first-time PIN only if the admin ticks that option.
  Residents who have are never touched.
- Opening balance: whole rubles, may be negative (an old debt). Entered
  once per resident (the database refuses a second one), so importing the
  file again never adds it twice.

The student code is the key: importing the same file twice changes nothing.
Files saved by Excel are understood: UTF-8 (with or without BOM) or
Windows-1251, separated by ";" or ",".
"""

import csv
import io
import re
from dataclasses import dataclass, field

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from . import initial_pins, services
from .models import Resident

MAX_FILE_BYTES = 1024 * 1024
MAX_ROWS = 5000
# Each first-time PIN takes a moment to hash; more than this would not finish
# within one request. Larger lists are imported in several files.
MAX_INITIAL_PINS = 500
MAX_OPENING_BALANCE = 100_000
FIELDS = ("student_code", "full_name", "room")
MAX_LENGTH = {"student_code": 32, "full_name": 200, "room": 20}

# Column titles we recognise (lower case, ru and en).
HEADERS = {
    "student_code": {
        "student_code",
        "student code",
        "code",
        "код",
        "студенческий код",
        "номер студенческого",
    },
    "full_name": {"full_name", "full name", "name", "фио", "имя", "фамилия имя", "фамилия, имя"},
    "room": {"room", "комната", "номер комнаты"},
    "birth_date": {"birth_date", "birth date", "date of birth", "дата рождения", "день рождения"},
    "opening_balance": {
        "opening_balance",
        "opening balance",
        "balance",
        "баланс",
        "начальный баланс",
        "остаток",
    },
}
# Other columns (e.g. an old "language" column) are ignored: residents choose
# their own language, and the app remembers it.

NEW, CHANGED, UNCHANGED, ERROR = "new", "changed", "unchanged", "error"


class ImportFileError(Exception):
    """The file as a whole cannot be read; the message is shown to the admin."""


@dataclass
class Row:
    line: int
    values: dict
    status: str = NEW
    errors: list = field(default_factory=list)
    changes: dict = field(default_factory=dict)  # field -> (old, new)
    resident: Resident | None = None
    # pepper(first-time PIN) when a date of birth was given; never the date.
    pin_digest: str | None = None
    opening: int | None = None  # whole rubles, never 0
    opening_already: bool = False  # the resident has one already: skipped
    renewable: bool = False  # existing, no own PIN yet, a date given

    @property
    def has_date(self):
        return self.pin_digest is not None

    @property
    def gets_opening(self):
        return self.opening is not None and not self.opening_already

    @property
    def name_changed(self):
        return "full_name" in self.changes


@dataclass
class Preview:
    rows: list

    def count(self, status):
        return sum(1 for row in self.rows if row.status == status)

    @property
    def to_apply(self):
        return [row for row in self.rows if row.status in (NEW, CHANGED)]

    def _with(self, status):
        return [row for row in self.rows if row.status == status]

    @property
    def new_rows(self):
        return self._with(NEW)

    @property
    def changed_rows(self):
        return self._with(CHANGED)

    @property
    def unchanged_rows(self):
        return self._with(UNCHANGED)

    @property
    def error_rows(self):
        return self._with(ERROR)

    @property
    def has_dates(self):
        return any(row.has_date for row in self.rows)

    @property
    def has_openings(self):
        return any(row.opening is not None for row in self.rows)

    @property
    def new_with_pin(self):
        return [row for row in self.new_rows if row.has_date]

    @property
    def new_with_link(self):
        return [row for row in self.new_rows if not row.has_date]

    @property
    def renewable_rows(self):
        return [row for row in self.rows if row.renewable]

    @property
    def opening_rows(self):
        return [row for row in self.rows if row.status != ERROR and row.gets_opening]

    @property
    def opening_total(self):
        return sum(row.opening for row in self.opening_rows)

    def has_work(self, renew_initial_pins=False):
        return bool(
            self.to_apply or self.opening_rows or (renew_initial_pins and self.renewable_rows)
        )


def _decode(data):
    if len(data) > MAX_FILE_BYTES:
        raise ImportFileError(_("The file is too large (more than 1 MB)."))
    for encoding in ("utf-8-sig", "cp1251"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ImportFileError(_("The file could not be read. Save it as CSV from Excel and try again."))


def _columns(header):
    """Map our field names to column positions using the header row."""
    positions = {}
    for index, title in enumerate(header):
        title = title.strip().lower()
        for name, titles in HEADERS.items():
            if title in titles and name not in positions:
                positions[name] = index
    missing = [n for n in ("student_code", "full_name", "room") if n not in positions]
    if missing:
        raise ImportFileError(
            _("The first row must name the columns: student code, full name and room.")
        )
    return positions


def _opening(text):
    """Whole rubles, e.g. "150", "-80", "1 200 ₽"; None if empty or 0."""
    cleaned = re.sub(r"[\s\u00a0]|₽|руб\.?|rub", "", text, flags=re.IGNORECASE)
    cleaned = cleaned.replace("\u2212", "-")  # the minus sign Excel sometimes uses
    if not cleaned:
        return None
    if not re.fullmatch(r"[+-]?\d+", cleaned):
        raise ValueError(_("the opening balance must be whole rubles, e.g. 150 or -80"))
    amount = int(cleaned)
    if abs(amount) > MAX_OPENING_BALANCE:
        raise ValueError(_("the opening balance is too large"))
    return amount or None


def _optional_columns(row, today):
    """Turn the date of birth into the PIN's digest at once (the date is
    removed from the row) and read the opening balance."""
    born = row.values.pop("birth_date", "")
    if born:
        try:
            row.pin_digest = initial_pins.digest_for(initial_pins.parse_birth_date(born, today))
        except initial_pins.BadDate as exc:
            row.errors.append(str(exc))
    balance = row.values.pop("opening_balance", "")
    if balance:
        try:
            row.opening = _opening(balance)
        except ValueError as exc:
            row.errors.append(str(exc))


def _read(data, today):
    text = _decode(data)
    first_line = text.split("\n", 1)[0]
    delimiter = ";" if first_line.count(";") >= first_line.count(",") else ","
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    try:
        header = next(reader)
    except StopIteration:
        raise ImportFileError(_("The file is empty.")) from None
    positions = _columns(header)
    rows = []
    for line, cells in enumerate(reader, start=2):
        if not any(cell.strip() for cell in cells):
            continue  # blank line
        if len(rows) >= MAX_ROWS:
            raise ImportFileError(_("The file has more than 5000 rows."))
        values = {
            name: cells[index].strip() if index < len(cells) else ""
            for name, index in positions.items()
        }
        row = Row(line=line, values=values)
        _optional_columns(row, today)
        rows.append(row)
    if not rows:
        raise ImportFileError(_("The file has no residents in it."))
    if sum(1 for row in rows if row.has_date) > MAX_INITIAL_PINS:
        raise ImportFileError(
            _("More than %(n)s dates of birth in one file: split it into smaller files.")
            % {"n": MAX_INITIAL_PINS}
        )
    return rows


def _check(row, seen_codes):
    values = row.values
    for name, label in (
        ("student_code", _("student code")),
        ("full_name", _("full name")),
        ("room", _("room")),
    ):
        if not values.get(name):
            row.errors.append(_("%(field)s is missing") % {"field": label})
        elif len(values[name]) > MAX_LENGTH[name]:
            row.errors.append(_("%(field)s is too long") % {"field": label})
    code = values.get("student_code", "").lower()
    if code:
        if code in seen_codes:
            row.errors.append(
                _("the same student code is already on line %(line)s") % {"line": seen_codes[code]}
            )
        else:
            seen_codes[code] = row.line


def preview(dormitory, data):
    """What importing `data` (bytes) would do. Writes nothing."""
    return _compare(dormitory, _read(data, timezone.localdate()))


def stored(result):
    """What is kept between preview and confirm: the rows without errors,
    with the PIN digests, never the file or any date of birth."""
    return [
        {
            "line": row.line,
            "values": {name: row.values.get(name, "") for name in FIELDS},
            "pin_digest": row.pin_digest,
            "opening": row.opening,
        }
        for row in result.rows
        if row.status != ERROR
    ]


def _from_stored(items):
    return [
        Row(
            line=item["line"],
            values=dict(item["values"]),
            pin_digest=item["pin_digest"],
            opening=item["opening"],
        )
        for item in items
    ]


def _compare(dormitory, rows):
    from apps.ledger.models import LedgerEntry

    existing = {
        r.student_code.lower(): r
        for r in Resident.objects.filter(
            dormitory=dormitory, anonymized_at__isnull=True
        ).select_related("user")
    }
    with_opening = set(
        LedgerEntry.objects.filter(
            resident__dormitory=dormitory, kind=LedgerEntry.Kind.OPENING
        ).values_list("resident_id", flat=True)
    )
    seen_codes = {}
    for row in rows:
        _check(row, seen_codes)
        if row.errors:
            row.status = ERROR
            continue
        resident = existing.get(row.values["student_code"].lower())
        if resident is None:
            row.status = NEW
            continue
        row.resident = resident
        row.opening_already = resident.pk in with_opening
        row.renewable = row.has_date and not initial_pins.is_activated(resident)
        for name in ("full_name", "room"):
            new = row.values.get(name)
            if new and new != getattr(resident, name):
                row.changes[name] = (getattr(resident, name), new)
        row.status = CHANGED if row.changes else UNCHANGED
    return Preview(rows)


def apply(actor, dormitory, data=None, *, rows=None, renew_initial_pins=False):
    """Import a file (`data`, bytes) or what `stored()` kept from its preview
    (`rows`): create new residents, update changed ones, give first-time PINs
    and opening balances. One transaction; rows with errors are skipped.
    Returns (preview, created)."""
    from apps.dorms import rules
    from apps.ledger import services as ledger_services

    days = rules.current().initial_pin_days
    with transaction.atomic():
        if rows is not None:
            result = _compare(dormitory, _from_stored(rows))
        else:
            result = preview(dormitory, data)
        created = []
        for row in result.rows:
            if row.status == ERROR:
                continue
            resident = row.resident
            if row.status == NEW:
                resident = services.create_resident(
                    actor=actor,
                    dormitory=dormitory,
                    full_name=row.values["full_name"],
                    room=row.values["room"],
                    student_code=row.values["student_code"],
                )
                created.append(resident)
            elif row.status == CHANGED:
                services.update_resident(
                    actor=actor,
                    resident=resident,
                    **{name: new for name, (_old, new) in row.changes.items()},
                )
            if row.has_date and (row.status == NEW or (renew_initial_pins and row.renewable)):
                initial_pins.set_initial_pin(
                    actor=actor, resident=resident, digest=row.pin_digest, days=days
                )
            if row.gets_opening:
                ledger_services.set_opening_balance(
                    actor=actor, resident=resident, amount=row.opening
                )
    return result, created
