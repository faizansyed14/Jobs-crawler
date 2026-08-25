from __future__ import annotations

import logging
from datetime import datetime, timezone
from html import unescape
from typing import Any, Iterator
from urllib.parse import urljoin

from config.portals import GulfTalentConfig, IndustryDef, LocationDef
from config.settings import get_settings
from core import live_status
from core.posted_date import (
    approximate_from_relative_text,
    parse_bare_calendar_date_inferred,
    parse_calendar_date_with_year,
    parse_job_posting_date_posted,
)
from core.rate_limiter import AdaptiveRateLimiter
from core.robots import RobotsGuard
from extractors.base import BaseExtractor, CrawlCancelled, JobListing
from extractors.gulftalent_client import GulfTalentAPIClient

logger = logging.getLogger(__name__)


def _pick(data: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in data and data[key] not in (None, ""):
            return data[key]
    return default


def _location_matches(row_location: str, location: LocationDef) -> bool:
    """Country-scoped category pages include sibling cities — keep selected city."""
    text = (row_location or "").strip().lower()
    if not text:
        return False
    label = location.label.strip().lower()
    key = location.key.replace("-", " ")
    api = location.api_value.replace("-", " ")
    if label and label in text:
        return True
    if key and key in text:
        return True
    if api and api in text:
        return True
    # Country-only labels (e.g. "UAE") when user picked a city — exclude
    country = location.country.strip().lower()
    if text == country:
        return False
    return False


class GulfTalentExtractor(BaseExtractor):
    portal_name = "gulftalent"

    def __init__(
        self,
        locations: list[str],
        industry: str | None = "it",
        *,
        config: GulfTalentConfig | None = None,
        max_pages: int | None = None,
    ) -> None:
        self.config = config or GulfTalentConfig()
        self.settings = get_settings()
        self.location_defs: list[LocationDef] = self.config.resolve_locations(locations)
        self.industry_def: IndustryDef | None = self.config.resolve_industry(industry)
        self.industry_key: str | None = None
        if industry and self.industry_def:
            normalized = industry.strip().lower().replace(" ", "_").replace("-", "_")
            self.industry_key = self.config.industry_aliases.get(normalized, normalized)
            if self.industry_key not in self.config.industries:
                self.industry_key = next(
                    (
                        k
                        for k, v in self.config.industries.items()
                        if v.cluster_ind == self.industry_def.cluster_ind
                    ),
                    None,
                )
        self.uncapped = max_pages is None
        self.max_pages = max_pages or self.settings.uncapped_max_pages
        self.max_pages_display: int | None = None if self.uncapped else self.max_pages
        self.api = GulfTalentAPIClient(self.config)
        self.rate_limiter = AdaptiveRateLimiter()
        self.robots = RobotsGuard(
            self.config.robots_url,
            allowed_prefixes=(
                "/jobs",
                "/api/jobs/",
                "/uae/",
                "/saudi-arabia/",
                "/qatar/",
                "/kuwait/",
                "/bahrain/",
                "/oman/",
                "/egypt/",
                "/jordan/",
                "/dubai/",
                "/abu-dhabi/",
                "/sharjah/",
                "/riyadh/",
                "/jeddah/",
                "/doha/",
                "/manama/",
                "/muscat/",
                "/cairo/",
                "/amman/",
                "/ras-al-khaimah/",
            ),
        )
        self.robots.load()
        self.last_extraction_method = "html"
        self.pages_crawled = 0
        self.jobs_seen = 0

        sample_url = self.config.listing_url(
            location=self.location_defs[0],
            industry_key=self.industry_key,
            page=1,
        )
        if not self.robots.allowed(sample_url):
            raise RuntimeError(f"robots allowlist blocks {sample_url}")

    def fetch_listings(self) -> Iterator[JobListing]:
        industry_value = self.industry_key or (
            self.industry_def.label if self.industry_def else None
        )
        consecutive_failures = 0
        total_failures = 0
        locations_total = len(self.location_defs)

        why_delay = (
            "Intentional polite delay — slows traffic to reduce rate-limits / CAPTCHA risk."
        )

        def _pl(page: int) -> str:
            return f"page {page}" if self.uncapped else f"page {page}/{self.max_pages}"

        def _check_cancel() -> None:
            if live_status.is_cancel_requested():
                raise CrawlCancelled("Cancelled by user")

        def _tick(remaining: float, total: float, *, label: str) -> None:
            _check_cancel()
            live_status.update_progress(
                phase="waiting",
                message=f"{label} — {remaining:.0f}s left of {total:.0f}s",
                why=why_delay,
                delay_seconds=round(total, 1),
                delay_remaining=round(remaining, 1),
                delay_reason=label,
            )

        def _wait_after_page_inserts(
            *, page: int, location_label: str, location_key: str
        ) -> None:
            if page >= self.max_pages:
                return
            label = (
                f"Page gap after inserts · page {page} · {location_label} "
                f"({self.settings.page_delay_min_seconds:.0f}–"
                f"{self.settings.page_delay_max_seconds:.0f}s random)"
            )
            live_status.update_progress(
                phase="waiting",
                message=label,
                why=(
                    "Random polite delay between pages. Timer starts only after "
                    "every job from the previous page is inserted."
                ),
                location=location_key,
                page=page,
                max_pages=self.max_pages_display,
                log=label,
            )
            slept = self.rate_limiter.wait_between_pages(
                reason=f"after page {page} inserts",
                on_tick=lambda rem, tot, lbl=label: _tick(rem, tot, label=lbl),
            )
            live_status.update_progress(
                delay_seconds=round(slept, 1),
                delay_remaining=0,
                log=f"Page gap finished ({slept:.0f}s)",
            )

        live_status.update_progress(
            phase="warming_up",
            message="Warming GulfTalent session",
            why="Establish cookies before HTML listing fetches.",
            page=0,
            max_pages=self.max_pages_display,
            locations_total=locations_total,
            log="Warming GulfTalent session",
        )
        self.api.warmup(self.location_defs[0], self.industry_key)
        slept = self.rate_limiter.wait_after_warmup(
            on_tick=lambda rem, tot: _tick(rem, tot, label="Post-warmup pause"),
        )
        live_status.update_progress(
            phase="waiting",
            message=f"Post-warmup pause finished ({slept:.0f}s)",
            delay_seconds=round(slept, 1),
            delay_remaining=0,
            log=f"Waited {slept:.0f}s after warmup",
        )

        for loc_index, location in enumerate(self.location_defs, start=1):
            _check_cancel()
            if loc_index > 1:
                label = f"City gap before {location.label}"
                live_status.update_progress(
                    phase="waiting",
                    message=label,
                    why=why_delay,
                    location=location.key,
                    location_index=loc_index,
                    log=label,
                )
                slept = self.rate_limiter.wait_between_locations(
                    on_tick=lambda rem, tot, lbl=label: _tick(rem, tot, label=lbl),
                )
                live_status.update_progress(
                    delay_seconds=round(slept, 1),
                    delay_remaining=0,
                    log=f"City gap done ({slept:.0f}s)",
                )

            listing_url = self.config.listing_url(
                location=location,
                industry_key=self.industry_key,
                page=1,
            )
            live_status.update_progress(
                phase="location",
                message=f"Starting location {location.label}",
                why="SSR category/industry pages (API search ignores filters).",
                location=location.key,
                location_index=loc_index,
                locations_total=locations_total,
                page=0,
                max_pages=self.max_pages_display,
                delay_seconds=None,
                delay_remaining=None,
                log=f"Start location {location.key} via {listing_url}",
            )

            empty_streak = 0
            for page in range(1, self.max_pages + 1):
                _check_cancel()

                page_url = self.config.listing_url(
                    location=location,
                    industry_key=self.industry_key,
                    page=page,
                )
                live_status.update_progress(
                    phase="fetching",
                    message=f"Fetching {location.label} · {_pl(page)}",
                    why="HTML table listing with Position / Location / Date / Company.",
                    location=location.key,
                    location_index=loc_index,
                    locations_total=locations_total,
                    page=page,
                    max_pages=self.max_pages_display,
                    delay_seconds=None,
                    delay_remaining=None,
                    log=f"GET {page_url}",
                )

                try:
                    payload = self.api.fetch_listing_page(
                        location=location,
                        industry_key=self.industry_key,
                        page=page,
                    )
                    self.rate_limiter.on_success()
                    consecutive_failures = 0
                    self.last_extraction_method = getattr(self.api, "last_method", "html")
                except Exception as exc:  # noqa: BLE001
                    consecutive_failures += 1
                    total_failures += 1
                    logger.exception("GulfTalent page fetch failed: %s", exc)
                    live_status.update_progress(
                        phase="retry",
                        message=f"Page {page} failed ({consecutive_failures}x) — backing off",
                        why="Backoff after failure before retrying.",
                        log=f"Fetch failed page {page}: {exc}",
                    )
                    if consecutive_failures >= self.settings.max_consecutive_failures:
                        raise RuntimeError(
                            f"Aborting after {consecutive_failures} consecutive listing failures"
                        ) from exc
                    slept = self.rate_limiter.wait(
                        reason="retry backoff",
                        on_tick=lambda rem, tot: _tick(rem, tot, label="Retry backoff"),
                    )
                    live_status.update_progress(
                        delay_seconds=round(slept, 1),
                        delay_remaining=0,
                    )
                    continue

                rows = [
                    row
                    for row in (payload.get("positions") or [])
                    if isinstance(row, dict)
                ]
                # Country-scoped industry/category pages include sibling cities.
                if self.industry_key:
                    matched = [
                        row
                        for row in rows
                        if _location_matches(str(_pick(row, "location") or ""), location)
                    ]
                else:
                    matched = rows

                self.pages_crawled += 1
                total = payload.get("total_results")
                live_status.update_progress(
                    phase="parsing",
                    message=(
                        f"Parsed {location.label} {_pl(page)} · "
                        f"{len(rows)} raw · {len(matched)} city-matched"
                        + (f" · total≈{total}" if total else "")
                    ),
                    why="Keep rows for selected city when listing is country-scoped.",
                    pages_crawled=self.pages_crawled,
                    page=page,
                    log=f"Parsed {len(matched)}/{len(rows)} GulfTalent jobs",
                )

                if not rows:
                    empty_streak += 1
                    if empty_streak >= self.settings.empty_page_stop_streak:
                        live_status.update_progress(
                            message=(
                                f"No more listings for {location.label} after "
                                f"{empty_streak} empty page(s) in a row"
                            ),
                            log=f"Stopping {location.label} — {empty_streak} consecutive empty pages",
                        )
                        break
                    live_status.update_progress(
                        message=(
                            f"Empty listing page for {location.label} — "
                            "trying one more page before giving up"
                        ),
                        log=f"Empty page {page} for {location.key} (streak {empty_streak})",
                    )
                    _wait_after_page_inserts(
                        page=page,
                        location_label=location.label,
                        location_key=location.key,
                    )
                    continue

                empty_streak = 0
                for raw in matched:
                    listing = self._normalize(
                        raw, location=location, industry=industry_value
                    )
                    if listing is None:
                        continue
                    self.jobs_seen += 1
                    yield listing

                # Stop when page returned fewer than a full page (end of results)
                if len(rows) < self.config.default_limit:
                    live_status.update_progress(
                        message=f"Short page — finished {location.label}",
                        log=f"Short page {page} ({len(rows)} rows)",
                    )
                    break

                _wait_after_page_inserts(
                    page=page,
                    location_label=location.label,
                    location_key=location.key,
                )

            if empty_streak and loc_index == locations_total:
                break

        if self.pages_crawled == 0 and total_failures > 0:
            raise RuntimeError(
                f"No pages fetched successfully ({total_failures} listing failures)."
            )

    def _resolve_posted_at(
        self,
        *,
        posted_text: Any,
        link: str,
        job_id: str,
    ) -> datetime:
        """Exact date — GulfTalent's listing 'DD Mon' text is enough on its own.

        GulfTalent shows no year and no '30+'-style bucket (confirmed live:
        every job, old or new, is a plain day+month). Inferring the year
        from today's date resolves it exactly with zero extra requests. The
        detail-page fetch below only exists as a safety net for the rare
        case that text is missing or in some other format entirely.
        """
        listing_date = parse_calendar_date_with_year(str(posted_text or ""))
        if listing_date:
            return listing_date

        inferred = parse_bare_calendar_date_inferred(str(posted_text or ""))
        if inferred:
            return inferred

        if link:
            last_exc: Exception | None = None
            for attempt in range(2):
                try:
                    self.rate_limiter.wait(
                        reason=f"GulfTalent detail date · {job_id} (try {attempt + 1})"
                    )
                    html = self.api.fetch_job_detail_html(link)
                    exact = parse_job_posting_date_posted(html)
                    if exact:
                        logger.info(
                            "GulfTalent job %s exact posted_at from job page: %s",
                            job_id,
                            exact.date().isoformat(),
                        )
                        return exact
                    last_exc = RuntimeError("job page had no JSON-LD datePosted")
                except Exception as exc:  # noqa: BLE001
                    last_exc = exc
                logger.warning(
                    "GulfTalent job-page date fetch attempt %s failed for %s: %s",
                    attempt + 1,
                    job_id,
                    last_exc,
                )

        approx = approximate_from_relative_text(str(posted_text or ""))
        if approx:
            logger.warning(
                "GulfTalent job %s — job page date unavailable, using approximate "
                "date from listing text %r (%s)",
                job_id,
                posted_text,
                approx.date().isoformat(),
            )
            return approx

        logger.warning(
            "GulfTalent job %s — no exact or approximate date found anywhere; "
            "keeping job with scrape time as last resort (not skipped)",
            job_id,
        )
        return datetime.now(timezone.utc)

    def _normalize(
        self,
        data: dict[str, Any],
        *,
        location: LocationDef,
        industry: str | None,
    ) -> JobListing | None:
        job_id = str(_pick(data, "id", default="") or "").strip()
        if not job_id:
            return None

        title = unescape(str(_pick(data, "title", default="") or "").strip())
        if not title:
            return None

        link = str(_pick(data, "link", default="") or "").strip()
        if link and not link.startswith("http"):
            link = urljoin(self.config.base_url + "/", link.lstrip("/"))
        if not link:
            link = f"{self.config.base_url}/{self.config.country_slug(location)}/jobs/job-{job_id}"

        posted_at = self._resolve_posted_at(
            posted_text=_pick(data, "posted_text", "posted_date"),
            link=link,
            job_id=job_id,
        )

        company_name = unescape(
            str(_pick(data, "company_name", default="Unknown") or "Unknown").strip()
        )

        return JobListing(
            source_portal=self.portal_name,
            job_id=job_id,
            title=title,
            company_name=company_name,
            location=unescape(str(_pick(data, "location", default="") or "").strip()),
            url=link,
            salary="",
            posted_at=posted_at,
            search_location=location.key,
            industry=industry,
            is_promoted=False,
        )

    def close(self) -> None:
        self.api.close()
