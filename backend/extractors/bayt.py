from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Iterator
from urllib.parse import urljoin

from config.portals import BaytConfig, IndustryDef, LocationDef
from config.settings import get_settings
from core import live_status
from core.date_parser import parse_unix_timestamp
from core.posted_date import (
    approximate_from_relative_text,
    parse_calendar_date_with_year,
    parse_job_posting_date_posted,
    parse_precise_relative_date,
)
from core.rate_limiter import AdaptiveRateLimiter
from core.robots import RobotsGuard
from extractors.base import BaseExtractor, CrawlCancelled, JobListing
from extractors.bayt_client import BaytClient

logger = logging.getLogger(__name__)


def _pick(data: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in data and data[key] not in (None, ""):
            return data[key]
    return default


class BaytExtractor(BaseExtractor):
    """Bayt extractor — browser-first due to Cloudflare on listing pages."""

    portal_name = "bayt"

    def __init__(
        self,
        locations: list[str],
        industry: str | None = "it",
        *,
        industries: list[str] | None = None,
        config: BaytConfig | None = None,
        max_pages: int | None = None,
    ) -> None:
        self.config = config or BaytConfig()
        self.settings = get_settings()
        self.location_defs: list[LocationDef] = self.config.resolve_locations(locations)

        selected = self.config.resolve_industry_keys(
            industry=industry, industries=industries
        )
        # Bayt splits "tech" into many disjoint SEO categories — selecting
        # "it" expands to the full tech set; other keys kept as-is, de-duped.
        _IT_CATEGORY_KEYS = [
            "it",
            "software",
            "cyber_security",
            "devops",
            "cloud_computing",
            "data_science",
            "artificial_intelligence",
            "network_engineering",
            "telecommunications",
            "it_support",
        ]
        category_keys: list[str] = []
        seen: set[str] = set()
        for key in selected:
            expand = _IT_CATEGORY_KEYS if key == "it" else [key]
            for cat in expand:
                if cat in self.config.industries and cat not in seen:
                    seen.add(cat)
                    category_keys.append(cat)
        self.category_keys: list[str | None] = category_keys or [None]
        self.selected_industries = selected
        self.industry_key = selected[0] if len(selected) == 1 else None
        self.industry_def = (
            self.config.industries.get(selected[0]) if selected else None
        )

        self.uncapped = max_pages is None
        self.max_pages = max_pages or self.settings.uncapped_max_pages
        self.max_pages_display: int | None = None if self.uncapped else self.max_pages
        self.api = BaytClient(self.config)
        self.rate_limiter = AdaptiveRateLimiter()
        self.robots = RobotsGuard(self.config.robots_url)
        self.robots.load()
        self.last_extraction_method = "browser"
        self.pages_crawled = 0
        self.jobs_seen = 0
        self._seen_job_ids: set[str] = set()

        sample_url = self.config.listing_url(
            location=self.location_defs[0],
            industry_key=self.category_keys[0],
            page=1,
        )
        if not self.robots.allowed(sample_url):
            raise RuntimeError(f"robots allowlist blocks {sample_url}")

    def fetch_listings(self) -> Iterator[JobListing]:
        consecutive_failures = 0
        total_failures = 0
        locations_total = len(self.location_defs)
        multi_category = len(self.category_keys) > 1

        def _category_label(category_key: str | None) -> str:
            if category_key and category_key in self.config.industries:
                return self.config.industries[category_key].label
            return "All"

        def _industry_value(category_key: str | None) -> str | None:
            if category_key:
                return category_key
            return self.industry_key or (
                self.industry_def.label if self.industry_def else None
            )

        def _loc_label(location: LocationDef, category_key: str | None) -> str:
            if not multi_category:
                return location.label
            return f"{location.label} ({_category_label(category_key)})"

        why_delay = (
            "Intentional polite delay — Bayt is Cloudflare-protected; slow pacing "
            "reduces challenge / block risk."
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
            *, page: int, location_key: str, loc_label: str
        ) -> None:
            if page >= self.max_pages:
                return
            label = (
                f"Page gap after inserts · page {page} · {loc_label} "
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
            message="Bayt uses browser fallback behind Cloudflare",
            why="curl often gets CF 403; headed Chrome loads SEO listing pages.",
            page=0,
            max_pages=self.max_pages_display,
            locations_total=locations_total,
            log="Bayt crawl starting (browser-capable transport)",
        )
        slept = self.rate_limiter.wait_after_warmup(
            on_tick=lambda rem, tot: _tick(rem, tot, label="Pre-crawl pause"),
        )
        live_status.update_progress(
            delay_seconds=round(slept, 1),
            delay_remaining=0,
            log=f"Pre-crawl pause done ({slept:.0f}s)",
        )

        unit_index = 0
        for loc_index, location in enumerate(self.location_defs, start=1):
            for category_key in self.category_keys:
                _check_cancel()
                unit_index += 1
                loc_label = _loc_label(location, category_key)

                if unit_index > 1:
                    label = f"Gap before {loc_label}"
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
                        log=f"Gap done ({slept:.0f}s)",
                    )

                listing_url = self.config.listing_url(
                    location=location,
                    industry_key=category_key,
                    page=1,
                )
                live_status.update_progress(
                    phase="location",
                    message=f"Starting {loc_label}",
                    why="SEO paths like /en/uae/jobs/information-technology-jobs-in-dubai/",
                    location=location.key,
                    location_index=loc_index,
                    locations_total=locations_total,
                    page=0,
                    max_pages=self.max_pages_display,
                    delay_seconds=None,
                    delay_remaining=None,
                    log=f"Start {location.key} ({_category_label(category_key)}) via {listing_url}",
                )

                empty_streak = 0
                for page in range(1, self.max_pages + 1):
                    _check_cancel()

                    page_url = self.config.listing_url(
                        location=location,
                        industry_key=category_key,
                        page=page,
                    )
                    live_status.update_progress(
                        phase="fetching",
                        message=f"Fetching Bayt · {loc_label} · {_pl(page)}",
                        why="HTML job cards (li[data-job-id]); Chrome if Cloudflare blocks curl.",
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
                            industry_key=category_key,
                            page=page,
                        )
                        self.rate_limiter.on_success()
                        consecutive_failures = 0
                        self.last_extraction_method = getattr(
                            self.api, "last_method", "browser"
                        )
                    except Exception as exc:  # noqa: BLE001
                        consecutive_failures += 1
                        total_failures += 1
                        logger.exception("Bayt page fetch failed: %s", exc)
                        live_status.update_progress(
                            phase="retry",
                            message=f"Page {page} failed ({consecutive_failures}x) — backing off",
                            why="Backoff after CF/block or browser failure.",
                            log=f"Fetch failed page {page}: {exc}",
                        )
                        if consecutive_failures >= self.settings.max_consecutive_failures:
                            raise RuntimeError(
                                f"Aborting after {consecutive_failures} consecutive Bayt failures"
                            ) from exc
                        self.rate_limiter.on_rate_limit()
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
                    self.pages_crawled += 1
                    total = payload.get("total_results")
                    live_status.update_progress(
                        phase="parsing",
                        message=(
                            f"Parsed {loc_label} {_pl(page)} · "
                            f"{len(rows)} jobs"
                            + (f" · total≈{total}" if total else "")
                        ),
                        why="Parse listing cards: title, company, location, salary, relative date.",
                        pages_crawled=self.pages_crawled,
                        page=page,
                        log=f"Parsed {len(rows)} Bayt jobs via {self.last_extraction_method}",
                    )

                    if not rows:
                        empty_streak += 1
                        if empty_streak >= self.settings.empty_page_stop_streak:
                            live_status.update_progress(
                                message=(
                                    f"No more Bayt results for {loc_label} after "
                                    f"{empty_streak} empty page(s) in a row"
                                ),
                                log=f"Stopping {loc_label} — {empty_streak} consecutive empty pages",
                            )
                            break
                        live_status.update_progress(
                            message=(
                                f"Empty listing for {loc_label} — "
                                "trying one more page before giving up"
                            ),
                            log=f"Empty page {page} for {location.key} (streak {empty_streak})",
                        )
                        _wait_after_page_inserts(
                            page=page,
                            location_key=location.key,
                            loc_label=loc_label,
                        )
                        continue

                    empty_streak = 0
                    for raw in rows:
                        raw_id = str(raw.get("id") or "").strip()
                        if raw_id and raw_id in self._seen_job_ids:
                            continue
                        listing = self._normalize(
                            raw,
                            location=location,
                            industry=_industry_value(category_key),
                        )
                        if listing is None:
                            continue
                        if raw_id:
                            self._seen_job_ids.add(raw_id)
                        self.jobs_seen += 1
                        yield listing

                    # Stop when Bayt has no more results — max_pages is a ceiling only.
                    if total is not None and total > 0 and len(rows) >= total and page == 1:
                        live_status.update_progress(
                            message=(
                                f"Bayt only has {total} jobs for this filter "
                                "(1 page)."
                            ),
                            log=f"Exhausted: total={total} on page 1",
                        )
                        break
                    if total is not None and total > 0:
                        # Typical Bayt page size from this response
                        per_page = max(len(rows), 1)
                        pages_available = (total + per_page - 1) // per_page
                        if page >= pages_available:
                            live_status.update_progress(
                                message=(
                                    f"Reached end of Bayt results "
                                    f"(~{total} jobs, {pages_available} page(s))"
                                ),
                                log=f"Exhausted after page {page}/{pages_available}",
                            )
                            break
                    elif len(rows) < 15 and page > 1:
                        # No total shown; short page after page 1 ≈ last page
                        live_status.update_progress(
                            message=f"Short page — finished {loc_label}",
                            log=f"Short page {page} ({len(rows)} rows)",
                        )
                        break

                    _wait_after_page_inserts(
                        page=page,
                        location_key=location.key,
                        loc_label=loc_label,
                    )

        if self.pages_crawled == 0 and total_failures > 0:
            raise RuntimeError(
                f"No Bayt pages fetched successfully ({total_failures} failures)."
            )

    def _resolve_posted_at(
        self,
        *,
        posted_epoch: Any,
        posted_text: Any,
        link: str,
        job_id: str,
    ) -> datetime:
        """Exact date — Bayt's listing card already has it, no fetch needed.

        Every job card carries `data-automation-jobactivedate="<unix epoch>"`
        — an exact timestamp straight from Bayt's own listing HTML, so no
        request beyond the listing page itself is required for the normal
        case. The relative-text parsing and detail-page fetch below only
        exist as a safety net if that attribute is ever missing/unparseable.
        """
        epoch_date = parse_unix_timestamp(posted_epoch)
        if epoch_date:
            return epoch_date

        listing_date = parse_calendar_date_with_year(str(posted_text or ""))
        if listing_date:
            return listing_date

        precise = parse_precise_relative_date(str(posted_text or ""))
        if precise:
            return precise

        if link:
            last_exc: Exception | None = None
            for attempt in range(2):
                try:
                    self.rate_limiter.wait(
                        reason=f"Bayt detail date · {job_id} (try {attempt + 1})"
                    )
                    html = self.api.fetch_job_detail_html(link)
                    exact = parse_job_posting_date_posted(html)
                    if exact:
                        logger.info(
                            "Bayt job %s exact posted_at from job page: %s",
                            job_id,
                            exact.date().isoformat(),
                        )
                        return exact
                    last_exc = RuntimeError("job page had no recognizable posted date")
                except Exception as exc:  # noqa: BLE001
                    last_exc = exc
                logger.warning(
                    "Bayt job-page date fetch attempt %s failed for %s: %s",
                    attempt + 1,
                    job_id,
                    last_exc,
                )

        approx = approximate_from_relative_text(str(posted_text or ""))
        if approx:
            logger.warning(
                "Bayt job %s — job page date unavailable, using approximate "
                "date from listing text %r (%s)",
                job_id,
                posted_text,
                approx.date().isoformat(),
            )
            return approx

        logger.warning(
            "Bayt job %s — no exact or approximate date found anywhere; "
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
        title = str(_pick(data, "title", default="") or "").strip()
        if not title:
            return None

        link = str(_pick(data, "link", default="") or "").strip()
        if link and not link.startswith("http"):
            link = urljoin(self.config.base_url + "/", link.lstrip("/"))
        if not link:
            link = (
                f"{self.config.base_url}/{self.config.locale}/"
                f"{self.config.country_slug(location)}/jobs/job-{job_id}/"
            )

        posted_at = self._resolve_posted_at(
            posted_epoch=_pick(data, "posted_epoch"),
            posted_text=_pick(data, "posted_text"),
            link=link,
            job_id=job_id,
        )

        return JobListing(
            source_portal=self.portal_name,
            job_id=job_id,
            title=title,
            company_name=str(
                _pick(data, "company_name", default="Unknown") or "Unknown"
            ).strip(),
            location=str(_pick(data, "location", default="") or "").strip()
            or location.label,
            url=link,
            salary=str(_pick(data, "salary", default="") or "").strip(),
            posted_at=posted_at,
            search_location=location.key,
            industry=industry,
            is_promoted=False,
        )

    def close(self) -> None:
        self.api.close()
