"""A booking as one calendar event, and the three ways to add it: Google
Calendar and Outlook.com (prefilled links the resident's browser opens in a
new tab) and an .ics file for Apple Calendar and every other app.

The links are plain navigation: our pages load nothing from Google or
Microsoft, so the self-only CSP stays. The event names the machine(s), the
time and the dormitory, never the resident. Times come from one Event, so all
three options always agree.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlencode

from django.utils.translation import gettext as _

GOOGLE = "https://calendar.google.com/calendar/render"
OUTLOOK = "https://outlook.live.com/calendar/0/deeplink/compose"


@dataclass
class Event:
    uid: str
    starts_at: datetime
    ends_at: datetime
    summary: str
    location: str
    machine_numbers: list
    dormitory: object


def can_share_event(groups):
    """Several machines booked together (same time, none cancelled) can be one event."""
    return bool(groups) and all(
        not g.is_cancelled and g.starts_at == groups[0].starts_at and g.ends_at == groups[0].ends_at
        for g in groups
    )


def event_for(groups, dormitory):
    """One event covering booking groups with the same time range. A group's
    consecutive slots on one machine are already one range."""
    machines = sorted((g.machine for g in groups), key=lambda m: m.number)
    if len(groups) == 1:
        uid = str(groups[0].group_id)
    else:
        ids = ",".join(sorted(str(g.group_id) for g in groups))
        uid = str(uuid.uuid5(uuid.NAMESPACE_URL, ids))
    return Event(
        uid=uid,
        starts_at=groups[0].starts_at,
        ends_at=groups[0].ends_at,
        summary=_("Laundry: %(machine)s") % {"machine": ", ".join(m.name for m in machines)},
        location=dormitory.name,
        machine_numbers=[m.number for m in machines],
        dormitory=dormitory,
    )


def _hour(moment):
    return f"{moment:%H}" if moment.minute == 0 else f"{moment:%H%M}"


def filename(event):
    """laundry-DEM-2026-10-29-14-18-M1.ics; several machines: ...-M1-M3.ics
    (every machine number listed). Local time; a booking ending at midnight
    ends at "00"."""
    tz = event.dormitory.tzinfo
    start, end = event.starts_at.astimezone(tz), event.ends_at.astimezone(tz)
    machines = "-".join(f"M{n}" for n in event.machine_numbers)
    return f"laundry-{event.dormitory.code}-{start:%Y-%m-%d}-{_hour(start)}-{_hour(end)}-{machines}.ics"


def google_url(event):
    def utc(moment):
        return f"{moment.astimezone(UTC):%Y%m%dT%H%M%SZ}"

    params = {
        "action": "TEMPLATE",
        "text": event.summary,
        "dates": f"{utc(event.starts_at)}/{utc(event.ends_at)}",
        "location": event.location,
    }
    return f"{GOOGLE}?{urlencode(params)}"


def outlook_url(event):
    tz = event.dormitory.tzinfo
    params = {
        "path": "/calendar/action/compose",
        "rru": "addevent",
        "subject": event.summary,
        "startdt": event.starts_at.astimezone(tz).isoformat(),
        "enddt": event.ends_at.astimezone(tz).isoformat(),
        "location": event.location,
    }
    return f"{OUTLOOK}?{urlencode(params)}"


def links(event, ics_url):
    """What the "Add to calendar" menu needs."""
    return {"google": google_url(event), "outlook": outlook_url(event), "ics": ics_url}
