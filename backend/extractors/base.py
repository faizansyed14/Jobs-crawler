from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Iterator, Optional

from pydantic import BaseModel, field_validator


class JobListing(BaseModel):
    """Minimal job record from any portal extractor."""

    source_portal: str
    job_id: str
    title: str
    company_name: str
    location: str = ""
    url: str
    salary: str = ""
    posted_at: datetime
    # Operational — which city filter produced this row
    search_location: Optional[str] = None
    industry: Optional[str] = None
    is_promoted: bool = False

    @field_validator("posted_at")
    @classmethod
    def ensure_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class CrawlCancelled(Exception):
    """Raised inside fetch_listings() when the user cancels a running crawl."""


class BaseExtractor(ABC):
    portal_name: str

    @abstractmethod
    def fetch_listings(self) -> Iterator[JobListing]:
        """Yield listings newest-first for configured locations/industry."""

    def close(self) -> None:
        return None