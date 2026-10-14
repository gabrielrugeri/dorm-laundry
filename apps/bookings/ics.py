"""Calendar files (.ics, RFC 5545) for a booking, so residents can add it to
any calendar app. Written by hand: the format is small and plain text.

Times are written in the dormitory's local time (e.g. Europe/Moscow, UTC+3)
with a matching VTIMEZONE block, so every calendar app shows the same wall-clock
time the booking screens show. The VTIMEZONE holds the zone's offset on the
booking date; that is exact for zones without daylight saving time, such as
Moscow.
"""

from datetime import UTC

from django.utils import timezone

CRLF = "\r\n"


def _escape(text):
    """Escape a TEXT value (RFC 5545 section 3.3.11)."""
    return (
        str(text)
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
    )


def _fold(line):
    """Split lines longer than 75 bytes; continuation lines start with a space."""
    parts, current = [], ""
    for char in line:
        if len((current + char).encode("utf-8")) > 75:
            parts.append(current)
            current = " " + char
        else:
            current += char
    parts.append(current)
    return CRLF.join(parts)


def _offset(delta):
    """timedelta(hours=3) -> "+0300"."""
    minutes = int(delta.total_seconds() // 60)
    sign = "+" if minutes >= 0 else "-"
    hours, minutes = divmod(abs(minutes), 60)
    return f"{sign}{hours:02d}{minutes:02d}"


def booking_calendar(group, dormitory, *, uid_domain, summary):
    """An .ics document with one event covering the group's booked slots."""
    tz = dormitory.tzinfo
    start = group.starts_at.astimezone(tz)
    end = group.ends_at.astimezone(tz)
    offset = _offset(start.utcoffset())
    local = "%Y%m%dT%H%M%S"
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Dorm Laundry//Booking//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "BEGIN:VTIMEZONE",
        f"TZID:{dormitory.timezone}",
        "BEGIN:STANDARD",
        "DTSTART:19700101T000000",
        f"TZOFFSETFROM:{offset}",
        f"TZOFFSETTO:{offset}",
        f"TZNAME:{_escape(start.tzname())}",
        "END:STANDARD",
        "END:VTIMEZONE",
        "BEGIN:VEVENT",
        f"UID:{group.group_id}@{uid_domain}",
        f"DTSTAMP:{timezone.now().astimezone(UTC):%Y%m%dT%H%M%SZ}",
        f"DTSTART;TZID={dormitory.timezone}:{start.strftime(local)}",
        f"DTEND;TZID={dormitory.timezone}:{end.strftime(local)}",
        f"SUMMARY:{_escape(summary)}",
        f"LOCATION:{_escape(dormitory.name)}",
        "END:VEVENT",
        "END:VCALENDAR",
    ]
    return CRLF.join(_fold(line) for line in lines) + CRLF
