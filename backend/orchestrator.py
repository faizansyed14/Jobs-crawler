from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field

from config.portals import get_portal_config
from config.settings import get_settings
from core import live_status
from database.db import init_db, session_scope
from database.repository import JobRepository
from extractors.base import BaseExtractor, CrawlCancelled, JobListing
from extractors.bayt import BaytExtractor
from extractors.gulftalent import GulfTalentExtractor
from extractors.naukrigulf import NaukrigulfExtractor

logger = logging.getLogger(__name__)
_settings = get_settings()


class DuplicateStopTracker:
    """Stop a crawl unit after N consecutive known jobs (title+company+date)."""

    def __init__(self, repo: JobRepository, threshold: int) -> None:
        self.repo = repo
        self.threshold = threshold
        self.streak = 0

    def reset(self) -> None:
        self.streak = 0

    def ingest(self, job: JobListing, result: CrawlResult) -> bool:
        """Store one job. Returns True when this unit should stop."""
        result.jobs_found += 1
        is_known = self.repo.is_known_job(job)
        inserted = self.repo.upsert_job(job)
        if inserted:
            result.jobs_new += 1
        live_status.bump_jobs(found=1, new=1 if inserted else 0)

        if is_known or not inserted:
            self.streak += 1
        else:
            self.streak = 0

        if self.streak >= self.threshold:
            result.stop_reason = "duplicate_streak"
            live_status.update_progress(
                phase="waiting",
                message=(
                    f"Auto-stop — {self.streak} known jobs in a row "
                    f"(same title, company, posted date)"
                ),
                why=(
                    "Re-crawl hit old listings; skipping rest of this "
                    "city/industry unit."
                ),
                log=(
                    f"Duplicate streak {self.streak}/{self.threshold} — "
                    "stopping unit"
                ),
            )
            return True
        return False


def _ingest_listings(
    extractor: BaseExtractor,
    repo: JobRepository,
    result: CrawlResult,
    tracker: DuplicateStopTracker,
) -> None:
    for job in extractor.fetch_listings():
        if tracker.ingest(job, result):
            break


@dataclass
class CrawlResult:
    portal: str
    locations: list[str]
    industry: str | None
    industries: list[str] = field(default_factory=list)
    jobs_found: int = 0
    jobs_new: int = 0
    pages_crawled: int = 0
    stop_reason: str = "completed"
    extraction_method: str = "api"
    error: str | None = None
    success: bool = True


@dataclass(frozen=True)
class CrawlUnit:
    """One portal × one city × one industry — the atomic crawl step."""

    portal: str
    location: str
    industry: str


def build_extractor(
    portal: str,
    locations: list[str],
    industry: str | None,
    max_pages: int | None = None,
    *,
    industries: list[str] | None = None,
) -> BaseExtractor:
    key = portal.strip().lower().replace(" ", "").replace("_", "").replace("-", "")
    if key in {"naukrigulf", "naukri"}:
        return NaukrigulfExtractor(
            locations=locations,
            industry=industry,
            max_pages=max_pages,
        )
    if key in {"gulftalent", "gulftalentcom"}:
        return GulfTalentExtractor(
            locations=locations,
            industry=industry,
            max_pages=max_pages,
        )
    if key in {"bayt", "baytcom"}:
        return BaytExtractor(
            locations=locations,
            industry=industry,
            industries=industries,
            max_pages=max_pages,
        )
    raise ValueError(f"Portal {portal!r} not implemented yet")


def _portal_key(portal: str) -> str:
    return portal.strip().lower().replace(" ", "").replace("_", "").replace("-", "")


def build_portal_units(
    portal: str,
    locations: list[str],
    industries: list[str] | None,
    *,
    all_industries: bool = False,
) -> list[CrawlUnit]:
    """City-major then industry units for one portal (skip unknown keys)."""
    cfg = get_portal_config(portal)
    valid_locs = [k for k in locations if _normalize_loc(k) in cfg.locations]
    if not valid_locs:
        return []

    if all_industries or not industries:
        ind_keys = list(cfg.industries.keys())
    else:
        ind_keys = []
        for raw in industries:
            try:
                resolved = cfg.resolve_industry_keys(industry=raw, industries=None)
            except ValueError:
                continue
            for key in resolved:
                if key not in ind_keys:
                    ind_keys.append(key)
        if not ind_keys:
            return []

    # Bayt "it" already expands to the tech category set inside the extractor —
    # don't schedule those sub-keys as separate units when "it" is present.
    if _portal_key(portal) in {"bayt", "baytcom"} and "it" in ind_keys:
        _IT_EXPAND = {
            "software",
            "cyber_security",
            "devops",
            "cloud_computing",
            "data_science",
            "artificial_intelligence",
            "network_engineering",
            "telecommunications",
            "it_support",
        }
        ind_keys = [k for k in ind_keys if k == "it" or k not in _IT_EXPAND]

    units: list[CrawlUnit] = []
    for loc in valid_locs:
        for ind in ind_keys:
            units.append(CrawlUnit(portal=portal, location=loc, industry=ind))
    return units


def _normalize_loc(raw: str) -> str:
    return raw.strip().lower().replace(" ", "-").replace("_", "-")


def interleave_portal_units(portal_queues: list[list[CrawlUnit]]) -> list[CrawlUnit]:
    """Round-robin across portals so load is spread: N→G→B→N→G→B…"""
    queues = [deque(q) for q in portal_queues if q]
    out: list[CrawlUnit] = []
    while any(queues):
        for q in queues:
            if q:
                out.append(q.popleft())
    return out


def build_distributed_schedule(
    portals: list[str],
    locations: list[str],
    industries: list[str] | None,
    *,
    all_industries: bool = False,
) -> list[CrawlUnit]:
    queues = [
        build_portal_units(
            portal,
            locations,
            industries,
            all_industries=all_industries,
        )
        for portal in portals
    ]
    return interleave_portal_units(queues)


def _run_units(
    *,
    units: list[CrawlUnit],
    max_pages: int | None,
    result: CrawlResult,
    run_label: str,
) -> None:
    with session_scope() as session:
        repo = JobRepository(session)
        run = repo.start_run(result.portal, result.locations, run_label)
        extractor: BaseExtractor | None = None
        total_units = len(units)
        dup_tracker = DuplicateStopTracker(
            repo, _settings.duplicate_stop_streak
        )

        try:
            for idx, unit in enumerate(units, start=1):
                if live_status.is_cancel_requested():
                    raise CrawlCancelled("Cancelled by user")

                live_status.update_progress(
                    phase="location",
                    message=(
                        f"Unit {idx}/{total_units}: {unit.portal} · "
                        f"{unit.location} · {unit.industry}"
                    ),
                    industry=unit.industry,
                    location=unit.location,
                    log=(
                        f"Distributed unit {idx}/{total_units} → "
                        f"{unit.portal}/{unit.location}/{unit.industry}"
                    ),
                )
                dup_tracker.reset()
                extractor = build_extractor(
                    unit.portal,
                    [unit.location],
                    unit.industry,
                    max_pages=max_pages,
                    industries=[unit.industry],
                )
                try:
                    _ingest_listings(extractor, repo, result, dup_tracker)
                    result.pages_crawled += getattr(extractor, "pages_crawled", 0)
                    result.extraction_method = getattr(
                        extractor, "last_extraction_method", "api"
                    )
                except CrawlCancelled:
                    raise
                except Exception as unit_exc:  # noqa: BLE001
                    # One unit's persistent failure (e.g. Bayt CF block) must
                    # not abort the other 1000+ units in a distributed sweep.
                    result.pages_crawled += getattr(extractor, "pages_crawled", 0)
                    logger.exception(
                        "Unit %s/%s (%s/%s/%s) failed — skipping: %s",
                        idx,
                        total_units,
                        unit.portal,
                        unit.location,
                        unit.industry,
                        unit_exc,
                    )
                    live_status.update_progress(
                        message=(
                            f"Unit {idx}/{total_units} failed "
                            f"({unit.portal}/{unit.location}/{unit.industry}) — "
                            f"skipping: {unit_exc}"
                        ),
                        log=f"Unit failed, skipping: {unit_exc}",
                    )
                finally:
                    extractor.close()
                    extractor = None

            if result.jobs_found == 0:
                result.stop_reason = "no_jobs"

            repo.finish_run(
                run,
                jobs_found=result.jobs_found,
                jobs_new=result.jobs_new,
                pages_crawled=result.pages_crawled,
                stop_reason=result.stop_reason,
                extraction_method=result.extraction_method,
                status="success",
            )
            for portal in {u.portal for u in units}:
                repo.update_crawl_state(
                    portal,
                    success=True,
                    locations=result.locations,
                    industry=run_label,
                    new_count=result.jobs_new,
                )
        except CrawlCancelled:
            result.success = True
            result.stop_reason = "cancelled"
            if extractor is not None:
                result.pages_crawled += getattr(extractor, "pages_crawled", 0)
                result.extraction_method = getattr(
                    extractor, "last_extraction_method", "api"
                )
                extractor.close()
                extractor = None
            logger.info(
                "Crawl cancelled: found=%s pages=%s",
                result.jobs_found,
                result.pages_crawled,
            )
            repo.finish_run(
                run,
                jobs_found=result.jobs_found,
                jobs_new=result.jobs_new,
                pages_crawled=result.pages_crawled,
                stop_reason="cancelled",
                extraction_method=result.extraction_method,
                status="cancelled",
            )
        except Exception as exc:  # noqa: BLE001
            result.success = False
            result.error = str(exc)
            result.stop_reason = "error"
            logger.exception("Crawl failed: %s", exc)
            pages = result.pages_crawled
            method = result.extraction_method
            if extractor is not None:
                pages += getattr(extractor, "pages_crawled", 0)
                method = getattr(extractor, "last_extraction_method", method)
                extractor.close()
                extractor = None
            result.pages_crawled = pages
            result.extraction_method = method
            repo.finish_run(
                run,
                jobs_found=result.jobs_found,
                jobs_new=result.jobs_new,
                pages_crawled=pages,
                stop_reason="error",
                extraction_method=method,
                error_message=str(exc),
                status="error",
            )


def run_crawl(
    *,
    portal: str = "naukrigulf",
    locations: list[str],
    industry: str | None = "it",
    industries: list[str] | None = None,
    max_pages: int | None = None,
) -> CrawlResult:
    """Crawl one portal — locations × industries sequentially."""
    init_db()
    cfg = get_portal_config(portal)
    industry_keys = cfg.resolve_industry_keys(
        industry=industry, industries=industries
    )
    industry_label = (
        industry_keys[0]
        if len(industry_keys) == 1
        else f"{len(industry_keys)} industries"
    )
    result = CrawlResult(
        portal=portal,
        locations=locations,
        industry=industry_label,
        industries=industry_keys,
    )
    live_status.reset_for_crawl(locations, industry_label, max_pages)

    # Bayt: keep one extractor for all selected categories (reuses Chrome).
    # Others: one unit per city×industry.
    if _portal_key(portal) in {"bayt", "baytcom"}:
        units = [
            CrawlUnit(portal=portal, location=loc, industry=industry_keys[0])
            for loc in locations
            if _normalize_loc(loc) in cfg.locations
        ]
        # Special: run Bayt with full industries list per city
        with session_scope() as session:
            repo = JobRepository(session)
            run = repo.start_run(portal, locations, industry_label)
            extractor: BaseExtractor | None = None
            dup_tracker = DuplicateStopTracker(
                repo, _settings.duplicate_stop_streak
            )
            try:
                for unit in units:
                    if live_status.is_cancel_requested():
                        raise CrawlCancelled("Cancelled by user")
                    live_status.update_progress(
                        phase="location",
                        message=f"Bayt · {unit.location} · {industry_label}",
                        industry=industry_label,
                        location=unit.location,
                        log=f"Bayt city {unit.location} ({len(industry_keys)} categories)",
                    )
                    dup_tracker.reset()
                    extractor = build_extractor(
                        portal,
                        [unit.location],
                        industry_keys[0],
                        max_pages=max_pages,
                        industries=industry_keys,
                    )
                    try:
                        _ingest_listings(extractor, repo, result, dup_tracker)
                        result.pages_crawled += getattr(
                            extractor, "pages_crawled", 0
                        )
                        result.extraction_method = getattr(
                            extractor, "last_extraction_method", "api"
                        )
                    finally:
                        extractor.close()
                        extractor = None
                if result.jobs_found == 0:
                    result.stop_reason = "no_jobs"
                repo.finish_run(
                    run,
                    jobs_found=result.jobs_found,
                    jobs_new=result.jobs_new,
                    pages_crawled=result.pages_crawled,
                    stop_reason=result.stop_reason,
                    extraction_method=result.extraction_method,
                    status="success",
                )
                repo.update_crawl_state(
                    portal,
                    success=True,
                    locations=locations,
                    industry=industry_label,
                    new_count=result.jobs_new,
                )
            except CrawlCancelled:
                result.success = True
                result.stop_reason = "cancelled"
                if extractor is not None:
                    result.pages_crawled += getattr(extractor, "pages_crawled", 0)
                    extractor.close()
                repo.finish_run(
                    run,
                    jobs_found=result.jobs_found,
                    jobs_new=result.jobs_new,
                    pages_crawled=result.pages_crawled,
                    stop_reason="cancelled",
                    extraction_method=result.extraction_method,
                    status="cancelled",
                )
            except Exception as exc:  # noqa: BLE001
                result.success = False
                result.error = str(exc)
                result.stop_reason = "error"
                logger.exception("Crawl failed: %s", exc)
                if extractor is not None:
                    result.pages_crawled += getattr(extractor, "pages_crawled", 0)
                    extractor.close()
                repo.finish_run(
                    run,
                    jobs_found=result.jobs_found,
                    jobs_new=result.jobs_new,
                    pages_crawled=result.pages_crawled,
                    stop_reason="error",
                    extraction_method=result.extraction_method,
                    error_message=str(exc),
                    status="error",
                )
        _finish(result, industry_keys)
        return result

    units = build_portal_units(
        portal, locations, industry_keys, all_industries=False
    )
    _run_units(
        units=units,
        max_pages=max_pages,
        result=result,
        run_label=industry_label,
    )
    _finish(result, industry_keys)
    return result


def run_distributed_crawl(
    *,
    portals: list[str],
    locations: list[str],
    industries: list[str] | None = None,
    all_industries: bool = False,
    max_pages: int | None = None,
) -> CrawlResult:
    """Round-robin portals: Naukri unit → GulfTalent unit → Bayt unit → …

    Spreads load so no single portal gets every city/industry in a row.
    Each unit is one portal + one city + one industry (Bayt 'it' still expands
    tech categories inside that unit).
    """
    init_db()
    normalized: list[str] = []
    for raw in portals:
        key = _portal_key(raw)
        if key in {"naukri", "naukrigulf"}:
            name = "naukrigulf"
        elif key in {"gulftalent", "gulftalentcom"}:
            name = "gulftalent"
        elif key in {"bayt", "baytcom"}:
            name = "bayt"
        else:
            name = raw.strip().lower()
        if name not in normalized:
            get_portal_config(name)  # validate
            normalized.append(name)

    units = build_distributed_schedule(
        normalized,
        locations,
        industries,
        all_industries=all_industries,
    )
    if not units:
        raise ValueError(
            "No crawl units — check that selected cities/industries exist "
            "on at least one selected portal"
        )

    label = (
        f"distributed · {len(normalized)} portals · {len(units)} units"
    )
    result = CrawlResult(
        portal="+".join(normalized),
        locations=locations,
        industry=label,
        industries=industries or [],
    )
    live_status.reset_for_crawl(locations, label, max_pages)
    live_status.update_progress(
        log=(
            f"Distributed schedule: {len(units)} units interleaved across "
            f"{', '.join(normalized)}"
        ),
    )
    _run_units(units=units, max_pages=max_pages, result=result, run_label=label)
    _finish(result, industries or [])
    return result


def _finish(result: CrawlResult, industry_keys: list[str]) -> None:
    body = {
        "portal": result.portal,
        "locations": result.locations,
        "industry": result.industry,
        "industries": result.industries or industry_keys,
        "jobs_found": result.jobs_found,
        "jobs_new": result.jobs_new,
        "pages_crawled": result.pages_crawled,
        "stop_reason": result.stop_reason,
        "extraction_method": result.extraction_method,
        "success": result.success,
        "error": result.error,
    }
    live_status.finish(
        result=body,
        error=result.error if not result.success else None,
    )
    logger.info(
        "Crawl done portal=%s found=%s new=%s pages=%s reason=%s",
        result.portal,
        result.jobs_found,
        result.jobs_new,
        result.pages_crawled,
        result.stop_reason,
    )
