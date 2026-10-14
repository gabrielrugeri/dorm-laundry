from datetime import date


class IsoDateConverter:
    """URL part like 2026-10-20, passed to the view as a datetime.date."""

    regex = r"\d{4}-\d{2}-\d{2}"

    def to_python(self, value):
        return date.fromisoformat(value)

    def to_url(self, value):
        return value.isoformat() if isinstance(value, date) else value
