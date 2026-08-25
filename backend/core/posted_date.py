from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator

from core.date_parser import parse_relative_date

_LD_JSON_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    flags=re.I | re.S,
)
_CALENDAR_WITH_YEAR_RE = re.compile(r"^(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})$")
_BARE_CALENDAR_RE = re.compile(r"^(\d{1,2})\s+([A-Za-z]+)$")
_PRECISE_RELATIVE_RE = re.compile(r"^(\d{1,2})\s*(minute|min|hour|day)s?\s*ago$")


def parse_iso_datetime(value: str) -> datetime | None:
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_calendar_date_with_year(text: str) -> datetime | None:
    """Listing text with an explicit year, e.g. '21 Aug 2026' — exact, no network."""
    raw = re.sub(r"\s+", " ", str(text or "")).strip()
    if not raw:
        return None
    if re.match(r"^\d{4}-\d{2}-\d{2}", raw):
        iso = parse_iso_datetime(raw)
        if iso:
            return iso
    m = _CALENDAR_WITH_YEAR_RE.match(raw)
    if not m:
        return None
    for fmt in ("%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def parse_bare_calendar_date_inferred(
    text: str, *, today: datetime | None = None
) -> datetime | None:
    """'DD Mon' listing date with no year (GulfTalent) — infer the year.

    GulfTalent never shows relative text or a year on the listing, just
    e.g. '21 Aug' — for every job, no matter how old. A job can never be
    posted in the future, so interpreting it in the current year and
    stepping back one year if that lands after today is exact for any
    realistic listing (jobs don't stay posted for a year+). No network
    call needed, unlike Bayt's day-count text which plateaus at '30+'.
    """
    raw = re.sub(r"\s+", " ", str(text or "")).strip()
    if not raw:
        return None
    today = today or datetime.now(timezone.utc)
    m = _BARE_CALENDAR_RE.match(raw)
    if not m:
        return None
    day, month_name = m.group(1), m.group(2)
    candidate: datetime | None = None
    for fmt in ("%d %b %Y", "%d %B %Y"):
        try:
            candidate = datetime.strptime(
                f"{day} {month_name} {today.year}", fmt
            ).replace(tzinfo=timezone.utc)
            break
        except ValueError:
            continue
    if candidate is None:
        return None
    if candidate.date() > today.date():
        candidate = candidate.replace(year=today.year - 1)
    return candidate


def parse_precise_relative_date(
    text: str, *, scraped_at: datetime | None = None
) -> datetime | None:
    """Relative text that's precise enough to trust without a detail-page fetch.

    Bayt/GulfTalent show real day-level precision ('1 day ago' .. '29 days
    ago', hours/minutes ago) right up until they plateau at a bucket — every
    job older than the cutoff shows the identical '30+ days ago' text. So:
      - 'today' / 'just now' / 'yesterday' / '<1-29> day(s) ago' /
        '<N> hour(s) ago' / '<N> minute(s) ago' -> exact, computed locally.
      - '30+ days ago', weeks/months ago, bare dates, anything else -> None,
        meaning ambiguous — caller should fetch the job's detail page.

    This is what keeps the crawl fast and low-risk: only the genuinely
    bucketed jobs need an extra request to the portal.
    """
    raw = re.sub(r"\s+", " ", str(text or "")).strip().lower()
    if not raw:
        return None
    scraped_at = scraped_at or datetime.now(timezone.utc)
    if raw in ("today", "just now"):
        return scraped_at
    if raw == "yesterday":
        return scraped_at - timedelta(days=1)
    if "+" in raw:
        return None
    m = _PRECISE_RELATIVE_RE.match(raw)
    if not m:
        return None
    n = int(m.group(1))
    unit = m.group(2)
    if unit == "day" and n >= 30:
        return None
    if unit.startswith("min"):
        return scraped_at - timedelta(minutes=n)
    if unit == "hour":
        return scraped_at - timedelta(hours=n)
    return scraped_at - timedelta(days=n)


def _iter_json_ld_nodes(html: str) -> Iterator[dict[str, Any]]:
    """Yield every JSON-LD node embedded in the page (script[type=ld+json])."""
    for match in _LD_JSON_RE.finditer(html or ""):
        raw = match.group(1).strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except ValueError:
            continue
        if isinstance(data, list):
            for node in data:
                if isinstance(node, dict):
                    yield node
        elif isinstance(data, dict):
            graph = data.get("@graph")
            if isinstance(graph, list):
                for node in graph:
                    if isinstance(node, dict):
                        yield node
            else:
                yield data


def _is_job_posting(node: dict[str, Any]) -> bool:
    node_type = node.get("@type")
    if isinstance(node_type, list):
        return "JobPosting" in node_type
    return node_type == "JobPosting"


def parse_job_posting_date_posted(html: str) -> datetime | None:
    """Exact posted date from the job page's own schema.org JobPosting markup.

    Bayt and GulfTalent both embed this JSON-LD block on every job detail
    page (it's what powers their Google Jobs listing), with an unambiguous
    ISO `datePosted` — reliable even when the listing card only shows vague
    text like '30+ days ago' or '11 days ago'.
    """
    for node in _iter_json_ld_nodes(html):
        if _is_job_posting(node):
            posted = node.get("datePosted")
            if posted:
                parsed = parse_iso_datetime(str(posted))
                if parsed:
                    return parsed
    return None


def approximate_from_relative_text(
    text: str, *, scraped_at: datetime | None = None
) -> datetime | None:
    """Last-resort estimate when the exact JSON-LD date truly can't be read.

    Only used if the job detail page is unreachable after retries — keeps the
    job (never dropped) with a best-effort date instead of an exact one.
    """
    raw = str(text or "").strip()
    if not raw:
        return None
    try:
        return parse_relative_date(raw, scraped_at=scraped_at)
    except ValueError:
        return None
