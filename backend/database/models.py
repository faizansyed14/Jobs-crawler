from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("source_portal", "job_id", name="uq_portal_job"),
        Index("idx_jobs_portal_posted", "source_portal", "posted_at"),
        Index("idx_jobs_active", "source_portal", "is_active"),
        Index("idx_jobs_search_location", "search_location"),
        Index("idx_jobs_industry", "industry"),
        Index("idx_jobs_fingerprint", "source_portal", "content_fingerprint"),
    )

    id: Mapped[Any] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    source_portal: Mapped[str] = mapped_column(String(50), nullable=False)
    job_id: Mapped[str] = mapped_column(String(100), nullable=False)

    title: Mapped[str] = mapped_column(String(500), nullable=False)
    company_name: Mapped[str] = mapped_column(String(500), nullable=False)
    location: Mapped[Optional[str]] = mapped_column(String(255))
    url: Mapped[str] = mapped_column(Text, nullable=False)
    salary: Mapped[Optional[str]] = mapped_column(String(255))
    posted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    search_location: Mapped[Optional[str]] = mapped_column(String(100))
    industry: Mapped[Optional[str]] = mapped_column(String(100))

    content_fingerprint: Mapped[Optional[str]] = mapped_column(String(64))

    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class CrawlState(Base):
    __tablename__ = "crawl_state"

    source_portal: Mapped[str] = mapped_column(String(50), primary_key=True)
    last_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[Optional[str]] = mapped_column(Text)
    last_locations: Mapped[Optional[str]] = mapped_column(Text)
    last_industry: Mapped[Optional[str]] = mapped_column(String(100))
    last_new_count: Mapped[int] = mapped_column(Integer, default=0)


class CrawlRun(Base):
    __tablename__ = "crawl_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_portal: Mapped[str] = mapped_column(String(50), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    locations: Mapped[Optional[str]] = mapped_column(Text)
    industry: Mapped[Optional[str]] = mapped_column(String(100))
    jobs_found: Mapped[int] = mapped_column(Integer, default=0)
    jobs_new: Mapped[int] = mapped_column(Integer, default=0)
    pages_crawled: Mapped[int] = mapped_column(Integer, default=0)
    stop_reason: Mapped[Optional[str]] = mapped_column(String(100))
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    extraction_method: Mapped[Optional[str]] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="running")