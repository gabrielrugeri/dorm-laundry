"""Importing residents from a CSV file (student code, name, room).

Two steps, so nothing is written until the admin has seen what will happen:

1. `preview(dormitory, data)` reads the file and compares every row with the
   residents already in the dormitory: new, changed (with before/after per
   field), unchanged, or error (with the reason). It writes nothing.
2. `apply(actor, dormitory, data)` reads the same file again and, in one
   transaction, creates the new residents and updates the changed ones
   through the resident services (one audit event per change). Rows with
   errors are skipped.

The student code is the key: importing the same file twice changes nothing.
Files saved by Excel are understood: UTF-8 (with or without BOM) or
Windows-1251, separated by ";" or ",".
"""

import csv
import io
from dataclasses import dataclass, field

from django.conf import settings
from django.db import transaction
from django.utils.translation import gettext as _

from . import services
from .models import Resident

MAX_FILE_BYTES = 1024 * 1024
MAX_ROWS = 5000
FIELDS = ("student_code", "full_name", "room", "language")
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
    "language": {"language", "lang", "язык"},
}

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


def _read(data):
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
        rows.append(Row(line=line, values=values))
    if not rows:
        raise ImportFileError(_("The file has no residents in it."))
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
    language = values.get("language", "")
    if language and language.lower() not in dict(settings.LANGUAGES):
        row.errors.append(_("unknown language “%(value)s” (use ru or en)") % {"value": language})
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
    rows = _read(data)
    existing = {
        r.student_code.lower(): r
        for r in Resident.objects.filter(
            dormitory=dormitory, anonymized_at__isnull=True
        ).select_related("user")
    }
    seen_codes = {}
    for row in rows:
        _check(row, seen_codes)
        if row.errors:
            row.status = ERROR
            continue
        if row.values.get("language"):
            row.values["language"] = row.values["language"].lower()
        resident = existing.get(row.values["student_code"].lower())
        if resident is None:
            row.status = NEW
            continue
        row.resident = resident
        for name in ("full_name", "room", "language"):
            new = row.values.get(name)
            if new and new != getattr(resident, name):
                row.changes[name] = (getattr(resident, name), new)
        row.status = CHANGED if row.changes else UNCHANGED
    return Preview(rows)


def apply(actor, dormitory, data):
    """Import `data`: create new residents, update changed ones. One
    transaction; rows with errors are skipped. Returns (preview, created)."""
    with transaction.atomic():
        result = preview(dormitory, data)
        created = []
        for row in result.to_apply:
            if row.status == NEW:
                created.append(
                    services.create_resident(
                        actor=actor,
                        dormitory=dormitory,
                        full_name=row.values["full_name"],
                        room=row.values["room"],
                        student_code=row.values["student_code"],
                        language=row.values.get("language") or "ru",
                    )
                )
            else:
                services.update_resident(
                    actor=actor,
                    resident=row.resident,
                    **{name: new for name, (_old, new) in row.changes.items()},
                )
    return result, created
