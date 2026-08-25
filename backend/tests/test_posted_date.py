from __future__ import annotations

from datetime import datetime, timezone

from core.posted_date import (
    approximate_from_relative_text,
    parse_bare_calendar_date_inferred,
    parse_calendar_date_with_year,
    parse_job_posting_date_posted,
    parse_precise_relative_date,
)


def test_listing_ignores_relative_and_bare_text():
    assert parse_calendar_date_with_year("30+ days ago") is None
    assert parse_calendar_date_with_year("5 days ago") is None
    assert parse_calendar_date_with_year("21 Aug") is None


def test_listing_accepts_calendar_with_year():
    dt = parse_calendar_date_with_year("21 Aug 2026")
    assert dt is not None
    assert dt.date().isoformat() == "2026-08-21"


def _wrap_ld_json(payload: str) -> str:
    return (
        "<html><head>"
        f'<script type="application/ld+json">{payload}</script>'
        "</head><body></body></html>"
    )


def test_parse_job_posting_date_bayt_style():
    html = _wrap_ld_json(
        '{"@context":"https://schema.org","@type":"JobPosting",'
        '"title":"IT Director","datePosted":"2026-07-08",'
        '"validThrough":"2026-11-05T00:00:00Z"}'
    )
    dt = parse_job_posting_date_posted(html)
    assert dt is not None
    assert dt.date().isoformat() == "2026-07-08"


def test_parse_job_posting_date_gulftalent_style_with_graph():
    html = _wrap_ld_json(
        '{"@type":"BreadcrumbList","itemListElement":[]}'
    ) + _wrap_ld_json(
        '{"@type":"JobPosting","datePosted":"2026-08-13T00:00:00+00:00"}'
    )
    dt = parse_job_posting_date_posted(html)
    assert dt is not None
    assert dt.date().isoformat() == "2026-08-13"


def test_parse_job_posting_date_missing_returns_none():
    html = _wrap_ld_json('{"@type":"BreadcrumbList","itemListElement":[]}')
    assert parse_job_posting_date_posted(html) is None
    assert parse_job_posting_date_posted("<html>no ld+json here</html>") is None


def test_precise_relative_date_handles_1_to_29_days_without_network():
    scraped_at = datetime(2026, 8, 24, tzinfo=timezone.utc)
    dt = parse_precise_relative_date("1 day ago", scraped_at=scraped_at)
    assert dt is not None and dt.date().isoformat() == "2026-08-23"
    dt2 = parse_precise_relative_date("29 days ago", scraped_at=scraped_at)
    assert dt2 is not None and dt2.date().isoformat() == "2026-07-26"
    dt3 = parse_precise_relative_date("3 hours ago", scraped_at=scraped_at)
    assert dt3 is not None
    dt4 = parse_precise_relative_date("yesterday", scraped_at=scraped_at)
    assert dt4 is not None and dt4.date().isoformat() == "2026-08-23"


def test_precise_relative_date_rejects_bucketed_30_plus():
    scraped_at = datetime(2026, 8, 24, tzinfo=timezone.utc)
    assert parse_precise_relative_date("30+ days ago", scraped_at=scraped_at) is None
    assert parse_precise_relative_date("45 days ago", scraped_at=scraped_at) is None
    assert parse_precise_relative_date("2 weeks ago", scraped_at=scraped_at) is None


def test_bare_calendar_date_inferred_same_year():
    today = datetime(2026, 8, 24, tzinfo=timezone.utc)
    dt = parse_bare_calendar_date_inferred("21 Aug", today=today)
    assert dt is not None
    assert dt.date().isoformat() == "2026-08-21"


def test_bare_calendar_date_inferred_rolls_back_a_year_if_future():
    today = datetime(2026, 1, 10, tzinfo=timezone.utc)
    dt = parse_bare_calendar_date_inferred("25 Dec", today=today)
    assert dt is not None
    assert dt.date().isoformat() == "2025-12-25"


def test_approximate_from_relative_text_is_last_resort_only():
    dt = approximate_from_relative_text("5 days ago")
    assert dt is not None
    dt2 = approximate_from_relative_text("21 Aug")
    assert dt2 is None
