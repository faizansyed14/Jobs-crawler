from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Select, delete, desc, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from core.job_fingerprint import job_content_fingerprint
from database.models import CrawlRun, CrawlState, Job
from extractors.base import JobListing


class JobRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def is_known_job(self, job: JobListing) -> bool:
        """True if DB already has this listing (job_id or title+company+date hash)."""
        fp = self._fingerprint(job)
        row = self.session.execute(
            select(Job.id)
            .where(
                Job.source_portal == job.source_portal,
                Job.job_id == job.job_id,
            )
            .limit(1)
        ).scalar_one_or_none()
        if row is not None:
            return True
        row = self.session.execute(
            select(Job.id)
            .where(
                Job.source_portal == job.source_portal,
                Job.content_fingerprint == fp,
            )
            .limit(1)
        ).scalar_one_or_none()
        return row is not None

    def upsert_job(self, job: JobListing) -> bool:
        """Insert or refresh last_seen. Returns True if newly inserted."""
        payload = self._to_row(job)
        fp = payload["content_fingerprint"]
        existing = self.session.execute(
            select(Job).where(
                Job.source_portal == job.source_portal,
                Job.job_id == job.job_id,
            )
        ).scalar_one_or_none()

        if existing is None:
            existing = self.session.execute(
                select(Job).where(
                    Job.source_portal == job.source_portal,
                    Job.content_fingerprint == fp,
                )
            ).scalar_one_or_none()

        if existing:
            existing.last_seen_at = datetime.now(timezone.utc)
            existing.is_active = True
            existing.title = payload["title"]
            existing.company_name = payload["company_name"]
            existing.location = payload["location"]
            existing.url = payload["url"]
            existing.salary = payload["salary"]
            existing.posted_at = payload["posted_at"]
            existing.search_location = payload["search_location"]
            existing.industry = payload["industry"]
            existing.content_fingerprint = fp
            if existing.job_id != job.job_id:
                existing.job_id = job.job_id
            self.session.flush()
            return False

        dialect = self.session.bind.dialect.name if self.session.bind else ""
        if dialect == "postgresql":
            stmt = pg_insert(Job).values(**payload)
            stmt = stmt.on_conflict_do_update(
                constraint="uq_portal_job",
                set_={
                    "last_seen_at": func.now(),
                    "is_active": True,
                    "title": stmt.excluded.title,
                    "company_name": stmt.excluded.company_name,
                    "location": stmt.excluded.location,
                    "url": stmt.excluded.url,
                    "salary": stmt.excluded.salary,
                    "posted_at": stmt.excluded.posted_at,
                },
            )
            self.session.execute(stmt)
            self.session.flush()
            return True

        self.session.add(Job(**payload))
        self.session.flush()
        return True

    def list_jobs(
        self,
        *,
        portal: str | None = None,
        location: str | None = None,
        industry: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Job]:
        stmt: Select[Any] = select(Job).where(Job.is_active.is_(True))
        if portal:
            stmt = stmt.where(Job.source_portal == portal)
        if location:
            stmt = stmt.where(Job.search_location == location)
        if industry:
            stmt = stmt.where(func.lower(Job.industry) == industry.lower())
        stmt = stmt.order_by(desc(Job.posted_at)).offset(offset).limit(limit)
        return list(self.session.execute(stmt).scalars().all())

    def count_jobs(
        self,
        *,
        portal: str | None = None,
        location: str | None = None,
        industry: str | None = None,
    ) -> int:
        stmt = select(func.count()).select_from(Job).where(Job.is_active.is_(True))
        if portal:
            stmt = stmt.where(Job.source_portal == portal)
        if location:
            stmt = stmt.where(Job.search_location == location)
        if industry:
            stmt = stmt.where(func.lower(Job.industry) == industry.lower())
        return int(self.session.execute(stmt).scalar() or 0)

    def delete_jobs(self, *, portal: str | None = None) -> int:
        """Hard-delete jobs from DB. portal=None clears all portals."""
        stmt = delete(Job)
        if portal:
            stmt = stmt.where(Job.source_portal == portal)
        result = self.session.execute(stmt)
        self.session.flush()
        return int(result.rowcount or 0)

    def update_crawl_state(
        self,
        portal: str,
        *,
        success: bool,
        error: str | None = None,
        locations: list[str] | None = None,
        industry: str | None = None,
        new_count: int = 0,
    ) -> None:
        now = datetime.now(timezone.utc)
        state = self.session.get(CrawlState, portal)
        if state is None:
            state = CrawlState(source_portal=portal)
            self.session.add(state)
        state.last_run_at = now
        if success:
            state.last_success_at = now
            state.last_error = None
            state.last_new_count = new_count
        else:
            state.last_error = error
        if locations is not None:
            state.last_locations = ",".join(locations)
        if industry is not None:
            state.last_industry = industry
        self.session.flush()

    def start_run(
        self,
        portal: str,
        locations: list[str],
        industry: str | None,
    ) -> CrawlRun:
        run = CrawlRun(
            source_portal=portal,
            started_at=datetime.now(timezone.utc),
            locations=",".join(locations),
            industry=industry,
            status="running",
        )
        self.session.add(run)
        self.session.flush()
        return run

    def finish_run(
        self,
        run: CrawlRun,
        *,
        jobs_found: int,
        jobs_new: int,
        pages_crawled: int,
        stop_reason: str,
        extraction_method: str,
        error_message: str | None = None,
        status: str = "success",
    ) -> None:
        run.ended_at = datetime.now(timezone.utc)
        run.jobs_found = jobs_found
        run.jobs_new = jobs_new
        run.pages_crawled = pages_crawled
        run.stop_reason = stop_reason
        run.extraction_method = extraction_method
        run.error_message = error_message
        run.status = status
        self.session.flush()

    def latest_runs(self, limit: int = 20) -> list[CrawlRun]:
        stmt = select(CrawlRun).order_by(desc(CrawlRun.started_at)).limit(limit)
        return list(self.session.execute(stmt).scalars().all())

    @staticmethod
    def _fingerprint(job: JobListing) -> str:
        return job_content_fingerprint(
            source_portal=job.source_portal,
            title=job.title,
            company_name=job.company_name,
            posted_at=job.posted_at,
        )

    @staticmethod
    def _to_row(job: JobListing) -> dict[str, Any]:
        fp = job_content_fingerprint(
            source_portal=job.source_portal,
            title=job.title,
            company_name=job.company_name,
            posted_at=job.posted_at,
        )
        return {
            "source_portal": job.source_portal,
            "job_id": job.job_id,
            "title": job.title,
            "company_name": job.company_name,
            "location": job.location or None,
            "url": job.url,
            "salary": job.salary or None,
            "posted_at": job.posted_at,
            "search_location": job.search_location,
            "industry": job.industry,
            "content_fingerprint": fp,
            "is_active": True,
        }