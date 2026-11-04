"""UTC timestamps as stored and shown: 2026-11-04T10:00:00Z (SPEC 12.1)."""

from datetime import UTC, datetime

TS_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def format_ts(dt: datetime) -> str:
    """Format a datetime as UTC with seconds and a Z suffix. Naive values are taken as UTC."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).strftime(TS_FORMAT)


def parse_ts(text: str) -> datetime:
    """Parse a timestamp written by format_ts. Returns an aware UTC datetime."""
    return datetime.strptime(text, TS_FORMAT).replace(tzinfo=UTC)
