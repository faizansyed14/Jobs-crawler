from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional
from urllib.parse import quote

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, Field

from config.portals import get_portal_config, list_portals
from config.settings import get_settings
from core import live_status
from core.excel_export import jobs_to_xlsx
from database.analytics import JobAnalytics
from database.db import init_db, session_scope
from database.repository import JobRepository
from orchestrator import CrawlResult, run_crawl

logger = logging.getLogger(__name__)
settings = get_settings()

app = FastAPI(
    title="Job Scraper API",
    version="1.0.0",
    description="Multi-portal Gulf job extraction — location + industry selectable",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class CrawlRequest(BaseModel):
    portal: str = "naukrigulf"
    locations: list[str] = Field(..., min_length=1)
    industry: Optional[str] = "it"
    # Multi-select (Auto Crawl). When set and non-empty, overrides `industry`.
    industries: Optional[list[str]] = None
    # None = uncapped: each city crawls until its own empty-page streak stops it.
    max_pages: Optional[int] = Field(default=None, ge=1, le=500)


class JobOut(BaseModel):
    job_id: str
    title: str
    company_name: str
    location: Optional[str] = None
    url: str
    salary: Optional[str] = None
    posted_at: datetime
    search_location: Optional[str] = None
    industry: Optional[str] = None
    source_portal: Optional[str] = None


def _result_body(result: CrawlResult) -> dict[str, Any]:
    return {
        "portal": result.portal,
        "locations": result.locations,
        "industry": result.industry,
        "industries": getattr(result, "industries", []) or [],
        "jobs_found": result.jobs_found,
        "jobs_new": result.jobs_new,
        "pages_crawled": result.pages_crawled,
        "stop_reason": result.stop_reason,
        "extraction_method": result.extraction_method,
        "success": result.success,
        "error": result.error,
    }


def _resolve_crawl_industries(payload: CrawlRequest) -> list[str]:
    cfg = get_portal_config(payload.portal)
    return cfg.resolve_industry_keys(
        industry=payload.industry,
        industries=payload.industries,
    )


@app.on_event("startup")
def on_startup() -> None:
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    init_db()
    logger.info("API ready")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/meta/portals")
def meta_portals() -> list[dict[str, str]]:
    return list_portals()


@app.get("/meta/locations")
def list_locations(portal: str = "naukrigulf") -> list[dict[str, Any]]:
    cfg = get_portal_config(portal)
    return [
        {
            "key": loc.key,
            "label": loc.label,
            "country": loc.country,
            "api_value": loc.api_value,
            "lat": loc.lat,
            "lng": loc.lng,
        }
        for loc in cfg.locations.values()
    ]


@app.get("/meta/industries")
def list_industries(portal: str = "naukrigulf") -> list[dict[str, str]]:
    cfg = get_portal_config(portal)
    return [
        {"key": key, "label": ind.label, "cluster_ind": ind.cluster_ind}
        for key, ind in cfg.industries.items()
    ]


@app.get("/meta/pacing")
def pacing_meta() -> dict[str, Any]:
    """Polite crawl timing — always available for UI estimates."""
    return {
        "min_delay_seconds": float(getattr(settings, "min_delay_seconds", 4)),
        "max_delay_seconds": float(getattr(settings, "max_delay_seconds", 30)),
        "location_gap_seconds": float(getattr(settings, "location_gap_seconds", 5)),
        "max_pages_per_run": int(getattr(settings, "max_pages_per_run", 20)),
        "note": (
            "Requests are sequential with delays to reduce CAPTCHA / rate-limit risk. "
            "100 pages does not burst the server."
        ),
    }


@app.get("/crawl/status")
def crawl_status() -> dict[str, Any]:
    return live_status.snapshot()


@app.post("/crawl/cancel")
def cancel_crawl() -> dict[str, Any]:
    if not live_status.is_running():
        raise HTTPException(status_code=409, detail="No crawl is running")
    live_status.request_cancel()
    return {
        "accepted": True,
        "message": "Cancel requested — stopping after the current request",
    }


def _run_crawl_task(payload: CrawlRequest) -> None:
    try:
        run_crawl(
            portal=payload.portal,
            locations=payload.locations,
            industry=payload.industry,
            industries=payload.industries,
            max_pages=payload.max_pages,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Background crawl failed")
        live_status.finish(result=None, error=str(exc))


@app.post("/crawl")
def start_crawl(payload: CrawlRequest, background: BackgroundTasks) -> dict[str, Any]:
    if live_status.is_running():
        raise HTTPException(status_code=409, detail="Crawl already running")
    try:
        get_portal_config(payload.portal).resolve_locations(payload.locations)
        industry_keys = _resolve_crawl_industries(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    uncapped = payload.max_pages is None
    industry_label = (
        industry_keys[0]
        if len(industry_keys) == 1
        else f"{len(industry_keys)} industries"
    )
    live_status.reset_for_crawl(payload.locations, industry_label, payload.max_pages)
    background.add_task(_run_crawl_task, payload)
    response: dict[str, Any] = {
        "accepted": True,
        "message": "Crawl started (sequential + polite delays)",
        "locations": payload.locations,
        "industry": industry_label,
        "industries": industry_keys,
        "max_pages": payload.max_pages,
        "mode": "auto" if uncapped else "fixed",
    }
    if uncapped:
        response["estimated_minutes"] = None
        response["note"] = (
            "Uncapped — each city stops on its own once it hits "
            f"{settings.empty_page_stop_streak} empty pages in a row."
        )
    else:
        response["estimated_minutes"] = round(
            (
                payload.max_pages
                * len(payload.locations)
                * max(1, len(industry_keys))
                * (settings.min_delay_seconds + 2)
            )
            / 60,
            1,
        )
    return response


@app.post("/crawl/sync")
def crawl_sync(payload: CrawlRequest) -> dict[str, Any]:
    if live_status.is_running():
        raise HTTPException(status_code=409, detail="Crawl already running")
    try:
        get_portal_config(payload.portal).resolve_locations(payload.locations)
        _resolve_crawl_industries(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        result = run_crawl(
            portal=payload.portal,
            locations=payload.locations,
            industry=payload.industry,
            industries=payload.industries,
            max_pages=payload.max_pages,
        )
        return _result_body(result)
    except Exception as exc:  # noqa: BLE001
        live_status.finish(result=None, error=str(exc))
        raise


def _normalize_portal_filter(portal: Optional[str]) -> str | None:
    if not portal:
        return None
    key = portal.strip().lower()
    if key in {"", "all", "*"}:
        return None
    return key


@app.get("/analytics/jobs")
def job_analytics(
    granularity: str = Query(default="day", pattern="^(day|week|month)$"),
    portal: Optional[str] = Query(default=None),
    location: Optional[str] = None,
    industry: Optional[str] = None,
    lookback: Optional[int] = Query(default=None, ge=1, le=366),
) -> dict[str, Any]:
    """Posting counts over time — sourced from jobs.posted_at in the DB."""
    portal_key = _normalize_portal_filter(portal)
    with session_scope() as session:
        payload = JobAnalytics(session).fetch(
            granularity=granularity,  # type: ignore[arg-type]
            portal=portal_key,
            location=location,
            industry=industry,
            lookback=lookback,
        )
    return payload


@app.get("/jobs")
def get_jobs(
    portal: Optional[str] = Query(default=None),
    location: Optional[str] = None,
    industry: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    portal_key = _normalize_portal_filter(portal)
    with session_scope() as session:
        repo = JobRepository(session)
        total = repo.count_jobs(portal=portal_key, location=location, industry=industry)
        rows = repo.list_jobs(
            portal=portal_key,
            location=location,
            industry=industry,
            limit=limit,
            offset=offset,
        )
        items = [
            JobOut(
                job_id=j.job_id,
                title=j.title,
                company_name=j.company_name,
                location=j.location,
                url=j.url,
                salary=j.salary,
                posted_at=j.posted_at,
                search_location=j.search_location,
                industry=j.industry,
                source_portal=j.source_portal,
            ).model_dump()
            for j in rows
        ]
    return {
        "total": total,
        "items": items,
        "limit": limit,
        "offset": offset,
        "has_more": offset + len(items) < total,
    }


@app.delete("/jobs")
def clear_jobs(
    portal: Optional[str] = Query(default=None),
) -> dict[str, Any]:
    """Delete stored jobs. Omit portal (or portal=all) to clear every portal."""
    portal_key = _normalize_portal_filter(portal)
    with session_scope() as session:
        repo = JobRepository(session)
        deleted = repo.delete_jobs(portal=portal_key)
    return {
        "deleted": deleted,
        "portal": portal_key or "all",
    }


@app.get("/jobs/export")
def export_jobs_excel(
    portal: Optional[str] = Query(default=None),
    location: Optional[str] = None,
    industry: Optional[str] = None,
    limit: int = Query(default=5000, ge=1, le=20000),
) -> Response:
    portal_key = _normalize_portal_filter(portal)
    with session_scope() as session:
        repo = JobRepository(session)
        rows = repo.list_jobs(
            portal=portal_key,
            location=location,
            industry=industry,
            limit=limit,
            offset=0,
        )
        payload = jobs_to_xlsx(rows)

    stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    portal_part = portal_key or "all"
    parts = ["jobs", portal_part, stamp]
    if location:
        parts.insert(2, location)
    if industry:
        parts.insert(2, industry)
    filename = "_".join(parts) + ".xlsx"

    return Response(
        content=payload,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"
        },
    )


@app.get("/runs")
def get_runs(limit: int = Query(default=20, ge=1, le=100)) -> list[dict[str, Any]]:
    with session_scope() as session:
        repo = JobRepository(session)
        runs = repo.latest_runs(limit=limit)
        return [
            {
                "id": r.id,
                "portal": r.source_portal,
                "started_at": r.started_at,
                "ended_at": r.ended_at,
                "locations": r.locations,
                "industry": r.industry,
                "jobs_found": r.jobs_found,
                "jobs_new": r.jobs_new,
                "pages_crawled": r.pages_crawled,
                "stop_reason": r.stop_reason,
                "status": r.status,
                "error_message": r.error_message,
            }
            for r in runs
        ]
