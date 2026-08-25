from __future__ import annotations

import logging
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Verified against live robots / known public listing paths.
# Live robots fetch often hangs behind CDN — use static allowlists per portal.
_DEFAULT_ALLOWED = (
    "/spapi/jobapi/",
    "/jobs-in-",
)

_PORTAL_ALLOWED: dict[str, tuple[str, ...]] = {
    "naukrigulf": (
        "/spapi/jobapi/",
        "/jobs-in-",
    ),
    "gulftalent": (
        "/api/jobs/",
        "/jobs",
        "/dubai/",
        "/abu-dhabi/",
        "/riyadh/",
        "/doha/",
        "/uae/",
        "/saudi-arabia/",
        "/qatar/",
    ),
    "bayt": (
        "/en/uae/jobs/",
        "/en/saudi-arabia/jobs/",
        "/en/qatar/jobs/",
        "/en/kuwait/jobs/",
        "/en/bahrain/jobs/",
        "/en/oman/jobs/",
        "/en/egypt/jobs/",
        "/en/jordan/jobs/",
    ),
}


class RobotsGuard:
    """Static allowlist for known-safe crawl paths."""

    def __init__(
        self,
        robots_url: str,
        user_agent: str | None = None,
        allowed_prefixes: tuple[str, ...] | None = None,
    ) -> None:
        self.robots_url = robots_url
        self.user_agent = user_agent or "GulfJobCrawler/1.0"
        host = urlparse(robots_url).netloc.lower()
        if allowed_prefixes is not None:
            self._allowed = allowed_prefixes
        elif "gulftalent" in host:
            self._allowed = _PORTAL_ALLOWED["gulftalent"]
        elif "naukrigulf" in host:
            self._allowed = _PORTAL_ALLOWED["naukrigulf"]
        elif "bayt" in host:
            self._allowed = _PORTAL_ALLOWED["bayt"]
        else:
            self._allowed = _DEFAULT_ALLOWED
        self._loaded = True

    def load(self) -> None:
        logger.info(
            "Using static robots allowlist (skip live fetch of %s)",
            self.robots_url,
        )

    def allowed(self, url: str) -> bool:
        path = urlparse(url).path or "/"
        return any(path.startswith(prefix) for prefix in self._allowed)
