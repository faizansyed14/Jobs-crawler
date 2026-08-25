from __future__ import annotations

import logging
from dataclasses import dataclass, field

from config.portals import get_portal_config
from core import live_status
from database.db import init_db, session_scope
from database.repository import JobRepository
from extractors.base import BaseExtractor, CrawlCancelled
from extractors.bayt import BaytExtractor
from extractors.gulftalent import GulfTalentExtractor
from extractors.naukrigulf import NaukrigulfExtractor

logger = logging.getLogger(__name__)


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


def run_crawl(
    *,
    portal: str = "naukrigulf",
    locations: list[str],
    industry: str | None = "it",
    industries: list[str] | None = None,
    max_pages: int | None = None,
) -> CrawlResult:
    """Crawl selected locations + industry(ies); upsert by job_id (dedup only).

    max_pages=None means uncapped — each city is crawled until the extractor's
    own empty-page streak stop kicks in, not a fixed page ceiling.

    industries (multi) takes precedence over industry (single). Bayt receives
    the full list in one extractor (one browser session). Other portals loop
    one industry at a time.
    """
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

    is_bayt = _portal_key(portal) in {"bayt", "baytcom"}
    # Bayt: one extractor for all categories (reuses Chrome session).
    # Others: one extractor per industry (API/HTML, cheap to restart).
    passes: list[tuple[str | None, list[str] | None]]
    if is_bayt:
        passes = [(industry_keys[0], industry_keys)]
    else:
        passes = [(key, None) for key in industry_keys]

    try:
        with session_scope() as session:
            repo = JobRepository(session)
            run = repo.start_run(portal, locations, industry_label)
            extractor: BaseExtractor | None = None

            try:
                for ind_key, ind_list in passes:
                    if live_status.is_cancel_requested():
                        raise CrawlCancelled("Cancelled by user")
                    live_status.update_progress(
                        industry=ind_key or industry_label,
                        log=(
                            f"Industry pass: {ind_key}"
                            if ind_list is None
                            else f"Industry sweep: {len(ind_list)} categories"
                        ),
                    )
                    extractor = build_extractor(
                        portal,
                        locations,
                        ind_key,
                        max_pages=max_pages,
                        industries=ind_list,
                    )
                    try:
                        for job in extractor.fetch_listings():
                            result.jobs_found += 1
                            inserted = repo.upsert_job(job)
                            if inserted:
                                result.jobs_new += 1
                            live_status.bump_jobs(
                                found=1, new=1 if inserted else 0
                            )
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
                    result.extraction_method = getattr(
                        extractor, "last_extraction_method", "api"
                    )
                    extractor.close()
                    extractor = None
                logger.info(
                    "Crawl cancelled by user: portal=%s found=%s pages=%s",
                    portal,
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
                repo.update_crawl_state(
                    portal,
                    success=True,
                    locations=locations,
                    industry=industry_label,
                    new_count=result.jobs_new,
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
                    method = getattr(
                        extractor, "last_extraction_method", method
                    )
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
                repo.update_crawl_state(
                    portal,
                    success=False,
                    error=str(exc),
                    locations=locations,
                    industry=industry_label,
                )
    finally:
        pass

    body = {
        "portal": result.portal,
        "locations": result.locations,
        "industry": result.industry,
        "industries": result.industries,
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
        "Crawl done portal=%s industries=%s found=%s new=%s pages=%s reason=%s",
        portal,
        industry_keys,
        result.jobs_found,
        result.jobs_new,
        result.pages_crawled,
        result.stop_reason,
    )
    return result
