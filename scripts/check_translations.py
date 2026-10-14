"""Fail if the Russian catalog has untranslated or fuzzy strings.

Run after `python manage.py makemessages -l ru -l en` (CI does this), so any new
string added in code without a Russian translation is caught.

English needs no translations: the msgids are already English.
"""

import sys
from pathlib import Path

import polib

PO_FILE = Path(__file__).resolve().parent.parent / "locale" / "ru" / "LC_MESSAGES" / "django.po"


def main():
    catalog = polib.pofile(str(PO_FILE))
    problems = [(e, "untranslated") for e in catalog.untranslated_entries()]
    problems += [(e, "fuzzy") for e in catalog.fuzzy_entries()]
    for entry, reason in problems:
        print(f"{reason}: {entry.msgid!r}")
    if problems:
        print(f"\n{len(problems)} problem(s) in {PO_FILE}")
        return 1
    print(f"OK: {len(catalog.translated_entries())} Russian strings translated.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
