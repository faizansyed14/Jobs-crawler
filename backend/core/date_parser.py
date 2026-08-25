from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone


def parse_unix_timestamp(value: int | str | float | None) -> datetime | None:
    if value is None or value == "" or value == 0:
        return None
    try:
        ts = int(float(value))
    except (TypeError, ValueError):
        return None
    if ts > 10_000_000_000:
        ts //= 1000
    return datetime.fromtimestamp(ts, tz=timezone.utc)


def parse_relative_date(raw_text: str, scraped_at: datetime | None = None) -> datetime:
    scraped_at = scraped_at or datetime.now(timezone.utc)
    text = raw_text.strip().lower()
    if "just now" in text or text == "today":
        return scraped_at
    if "yesterday" in text:
        return scraped_at - timedelta(days=1)

    match = re.match(r"(\d+)\+?\s*(min|minute|hour|day|week|month)s?\s*ago", text)
    if not match:
        raise ValueError(f"Unrecognized posted-date format: {raw_text!r}")

    n = int(match.group(1))
    unit = match.group(2)
    if unit.startswith("min"):
        delta = timedelta(minutes=n)
    elif unit.startswith("hour"):
        delta = timedelta(hours=n)
    elif unit.startswith("day"):
        delta = timedelta(days=n)
    elif unit.startswith("week"):
        delta = timedelta(weeks=n)
    else:
        delta = timedelta(days=30 * n)
    return scraped_at - delta
