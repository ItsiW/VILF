"""Human-readable dates for the admin, independent of the server timezone."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

PACIFIC = ZoneInfo("America/Los_Angeles")


def human_datetime(value):
    if not value:
        return "—"
    try:
        date = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
        if date.tzinfo is None:
            date = date.replace(tzinfo=UTC)
        date = date.astimezone(PACIFIC)
    except (ValueError, TypeError, AttributeError):
        return "Unknown date"
    return f"{date:%b} {date.day}, {date.year} at {date.hour % 12 or 12}:{date:%M %p %Z}"
