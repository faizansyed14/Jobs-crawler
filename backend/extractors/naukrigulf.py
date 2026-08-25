from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Iterator
from urllib.parse import urljoin

from config.portals import IndustryDef, LocationDef, NaukrigulfConfig
from config.settings import get_settings
from core.date_parser import parse_unix_timestamp
from core import live_status
from core.rate_limiter import AdaptiveRateLimiter
from core.robots import RobotsGuard
from extractors.api_client import NaukrigulfAPIClient
from extractors.base import BaseExtractor, CrawlCancelled, JobListing

logger = logging.getLogger(__name__)


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _pick(data: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in data and data[key] not in (None, ""):
            return data[key]
    return default


def _salary_text(data: dict[str, Any]) -> str:
    compensation = _pick(data, "compensation", "Compensation", default={}) or {}
    if isinstance(compensation, dict):
        lo = _pick(compensation, "MinCtc", "minCtc", "jobMinCurrency", default="")
        hi = _pick(compensation, "MaxCtc", "maxCtc", "jobMaxCurrency", default="")
        hidden = _as_bool(_pick(compensation, "IsCtcHidden", "isCtcHidden"))
        if hidden:
            return ""
        parts = [str(x).strip() for x in (lo, hi) if x and str(x).strip().lower() != "true"]
        if parts:
            return " - ".join(parts) if len(parts) > 1 else parts[0]
    direct = _pick(data, "salary", "Salary", "ctc", default="")
    return str(direct or "").strip()


class NaukrigulfExtractor(BaseExtractor):
    portal_name = "naukrigulf"

    def __init__(
        self,
        locations: list[str],
        industry: str | None = "it",
        *,
        config: NaukrigulfConfig | None = None,
        max_pages: int | None = None,
    ) -> None:
        self.config = config or NaukrigulfConfig()
        self.settings = get_settings()
        self.location_defs: list[LocationDef] = self.config.resolve_locations(locations)
        self.industry_def: IndustryDef | None = self.config.resolve_industry(industry)
        self.industry_key: str | None = None
        if industry and self.industry_def:
            # Keep the caller's key (it), not the display label (IT).
            normalized = industry.strip().lower().replace(" ", "_").replace("-", "_")
            aliases = {
                "information_technology": "it",
                "tech": "it",
                "banking_and_finance": "banking",
                "realestate": "real_estate",
            }
            self.industry_key = aliases.get(normalized, normalized)
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
        self.api = NaukrigulfAPIClient(self.config)
        self.rate_limiter = AdaptiveRateLimiter()
        self.robots = RobotsGuard(self.config.robots_url)
        self.robots.load()
        self.last_extraction_method = "api"
        self.pages_crawled = 0
        self.jobs_seen = 0

        if not self.robots.allowed(self.config.search_url):
            raise RuntimeError(f"robots.txt disallows {self.config.search_url}")

    def fetch_listings(self) -> Iterator[JobListing]:
        freshness = self.config.default_freshness
        cluster_ind = self.industry_def.cluster_ind if self.industry_def else None
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
            """Pause before the next page — only after all jobs from this page are yielded."""
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
            message="Warming session cookies before first API call",
            why="Looks more like a normal browser visit before search requests.",
            page=0,
            max_pages=self.max_pages_display,
            locations_total=locations_total,
            log="Warming Naukrigulf session",
        )
        self.api.warmup(location=self.location_defs[0].api_value)
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

        for loc_idx, location in enumerate(self.location_defs, start=1):
            _check_cancel()
            if loc_idx > 1:
                label = f"City gap before {location.label}"
                live_status.update_progress(
                    phase="waiting",
                    message=label,
                    why=why_delay,
                    location=location.key,
                    location_index=loc_idx,
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

            logger.info(
                "Crawling %s location=%s industry=%s freshness=%s",
                self.portal_name,
                location.key,
                industry_value or "all",
                freshness,
            )
            live_status.update_progress(
                phase="location",
                message=(
                    f"Next city → {location.label} "
                    f"({loc_idx}/{locations_total}) — starting at {_pl(1)}"
                ),
                why=(
                    "Locations run one-by-one. Page number resets per city "
                    "(not continuing Dubai’s page count)."
                ),
                location=location.key,
                location_index=loc_idx,
                locations_total=locations_total,
                page=0,
                delay_seconds=None,
                delay_remaining=None,
                log=(
                    f"Location queue → {location.label} "
                    f"({loc_idx}/{locations_total}) · page counter reset to 1"
                ),
            )

            empty_streak = 0
            for page in range(1, self.max_pages + 1):
                _check_cancel()

                live_status.update_progress(
                    phase="fetching",
                    message=f"Calling search API · {_pl(page)} · {location.label}",
                    why="Fetching public job listings for this page.",
                    location=location.key,
                    location_index=loc_idx,
                    page=page,
                    max_pages=self.max_pages_display,
                    delay_seconds=None,
                    delay_remaining=None,
                    delay_reason=None,
                    log=f"GET search {_pl(page)} ({location.label})",
                )

                try:
                    payload = self.api.search_jobs(
                        location=location.api_value,
                        freshness_days=freshness,
                        page=page,
                        cluster_ind=cluster_ind,
                        sort_by_date=True,
                    )
                    self.rate_limiter.on_success()
                    consecutive_failures = 0
                    self.last_extraction_method = getattr(self.api, "last_method", "api")
                except Exception as exc:  # noqa: BLE001
                    consecutive_failures += 1
                    total_failures += 1
                    logger.exception("API page fetch failed: %s", exc)
                    live_status.update_progress(
                        phase="retry",
                        message=f"Page {page} failed ({consecutive_failures}x) — backing off",
                        why="Backoff after failure before retrying the same page.",
                        log=f"Fetch failed page {page}: {exc}",
                    )
                    if consecutive_failures >= self.settings.max_consecutive_failures:
                        raise RuntimeError(
                            f"Aborting after {consecutive_failures} consecutive API failures"
                        ) from exc
                    slept = self.rate_limiter.wait(
                        reason="retry backoff",
                        on_tick=lambda rem, tot: _tick(
                            rem, tot, label="Retry backoff"
                        ),
                    )
                    live_status.update_progress(
                        delay_seconds=round(slept, 1),
                        delay_remaining=0,
                    )
                    continue

                jobs = self._extract_job_rows(payload)
                self.pages_crawled += 1
                live_status.update_progress(
                    phase="parsing",
                    message=(
                        f"Parsed {_pl(page)} · {location.label} · "
                        f"{len(jobs)} rows"
                    ),
                    why="Normalizing titles, companies, salaries into local DB.",
                    pages_crawled=self.pages_crawled,
                    page=page,
                    log=f"Parsed {len(jobs)} jobs from page {page}",
                )

                if not jobs:
                    empty_streak += 1
                    logger.info(
                        "Empty page %s for %s (streak=%s/%s)",
                        page,
                        location.key,
                        empty_streak,
                        self.settings.empty_page_stop_streak,
                    )
                    if empty_streak >= self.settings.empty_page_stop_streak:
                        live_status.update_progress(
                            message=(
                                f"No more Naukri results for {location.label} "
                                f"after {empty_streak} empty page(s) in a row — "
                                "next city (page counter resets)"
                            ),
                            why=(
                                "Each location has its own page 1…N. "
                                f"{self.settings.empty_page_stop_streak} consecutive empty "
                                "pages means this city is done, not a rewind."
                            ),
                            log=(
                                f"Stopping {location.label} — "
                                f"{empty_streak} consecutive empty pages"
                            ),
                        )
                        break
                    live_status.update_progress(
                        message=(
                            f"Empty page {page} for {location.label} — "
                            "trying one more page before giving up on this city"
                        ),
                        log=f"Empty page {page} for {location.label} (streak {empty_streak})",
                    )
                    _wait_after_page_inserts(
                        page=page,
                        location_label=location.label,
                        location_key=location.key,
                    )
                    continue

                empty_streak = 0
                for raw in jobs:
                    listing = self._normalize(
                        raw, location=location, industry=industry_value
                    )
                    if listing is None:
                        continue
                    self.jobs_seen += 1
                    yield listing

                _wait_after_page_inserts(
                    page=page,
                    location_label=location.label,
                    location_key=location.key,
                )

        if self.pages_crawled == 0 and total_failures > 0:
            raise RuntimeError(
                f"No pages fetched successfully ({total_failures} API failures). "
                "Check network / Akamai block."
            )

    def _extract_job_rows(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        rows = payload.get("jobs") or payload.get("Jobs") or []
        out: list[dict[str, Any]] = []
        for row in rows:
            if isinstance(row, dict) and "Job" in row and isinstance(row["Job"], dict):
                out.append(row["Job"])
            elif isinstance(row, dict):
                out.append(row)
        return out

    def _normalize(
        self,
        data: dict[str, Any],
        *,
        location: LocationDef,
        industry: str | None,
    ) -> JobListing | None:
        job_id = str(_pick(data, "jobId", "JobId", default="") or "").strip()
        if not job_id:
            return None

        company = _pick(data, "company", "Company", default={}) or {}
        if not isinstance(company, dict):
            company = {"name": str(company)}

        posted_raw = _pick(data, "latestPostedDate", "LatestPostedDate", "PostedDate")
        posted_at = parse_unix_timestamp(posted_raw)
        if posted_at is None:
            logger.warning("Skipping job %s — missing posted date", job_id)
            return None

        jd_url = str(_pick(data, "jdURL", "JdURL", default="") or "")
        if jd_url and not jd_url.startswith("http"):
            jd_url = urljoin(self.config.base_url + "/", jd_url.lstrip("/"))
        if not jd_url:
            jd_url = f"{self.config.base_url}/job-{job_id}"

        title = str(_pick(data, "designation", "Designation", default="") or "").strip()
        company_name = str(
            _pick(company, "name", "Name", default="Unknown") or "Unknown"
        ).strip()
        if not title:
            return None

        promoted = (
            _as_bool(_pick(data, "isPremium", "IsPremium"))
            or _as_bool(_pick(data, "isSponsoredJob", "IsSponsored"))
            or _as_bool(_pick(data, "isTopEmployer", "IsTopEmployer"))
            or _as_bool(_pick(data, "isFeaturedEmployer", "IsFeaturedEmployer"))
        )

        return JobListing(
            source_portal=self.portal_name,
            job_id=job_id,
            title=title,
            company_name=company_name,
            location=str(_pick(data, "location", "Location", default="") or "").strip(),
            url=jd_url,
            salary=_salary_text(data),
            posted_at=posted_at,
            search_location=location.key,
            industry=industry,
            is_promoted=promoted,
        )

    def close(self) -> None:
        self.api.close()