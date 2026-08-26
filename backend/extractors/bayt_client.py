from __future__ import annotations

import logging
import re
from html import unescape
from typing import Any
from urllib.parse import urljoin

from config.portals import BaytConfig, LocationDef
from config.settings import get_settings
from core.html_totals import largest_jobs_found_count
from core.session_manager import CookieJar

logger = logging.getLogger(__name__)

_LI_RE = re.compile(
    r'<li[^>]*data-job-id="(?P<id>\d+)"[^>]*>(?P<body>.*?)</li>',
    flags=re.I | re.S,
)
_TITLE_RE = re.compile(
    r'<a[^>]*data-js-aid="jobID"[^>]*href="(?P<href>[^"]+)"[^>]*'
    r'(?:title="(?P<title_attr>[^"]*)")?[^>]*>\s*(?P<title>[^<]+)\s*</a>',
    flags=re.I | re.S,
)
_TITLE_ALT_RE = re.compile(
    r'href="(?P<href>/[^"]+/jobs/[^"]+-(?P<id>\d+)/?)"[^>]*'
    r'(?:title="(?P<title_attr>[^"]*)")?[^>]*>\s*(?P<title>[^<]+)\s*</a>',
    flags=re.I | re.S,
)
_COMPANY_RE = re.compile(
    r'class="job-company-location-wrapper"[^>]*>.*?<a[^>]*>\s*(?P<company>[^<]+)\s*</a>',
    flags=re.I | re.S,
)
_LOCATION_RE = re.compile(
    r'jb-label-location[^>]*>.*?<span>\s*(?P<city>[^<]+)\s*</span>',
    flags=re.I | re.S,
)
_SALARY_RE = re.compile(
    r'jb-label-salary[^>]*>.*?</i>\s*(?P<salary>[^<]+)',
    flags=re.I | re.S,
)
_DATE_EPOCH_RE = re.compile(
    r'data-automation-jobactivedate="(?P<epoch>\d+)"',
    flags=re.I,
)
_DATE_TEXT_RE = re.compile(
    r'data-automation-id="job-active-date"[^>]*>\s*(?P<date>[^<]+?)\s*<',
    flags=re.I | re.S,
)
_TOTAL_RE = re.compile(
    r"([\d.,]+)\s*([Kk])?\s+jobs?\s+found",
    flags=re.I,
)


class BaytClient:
    """Bayt listing client — curl first, headed Chrome on Cloudflare 403."""

    def __init__(self, config: BaytConfig | None = None) -> None:
        self.config = config or BaytConfig()
        self.settings = get_settings()
        self.cookies = CookieJar(self.config.name)
        self._curl_session = None
        self._browser_session = None  # lazy NodriverSession, reused across calls
        self.last_method = "browser"
        self._init_transport()

    def _init_transport(self) -> None:
        try:
            from curl_cffi import CurlHttpVersion
            from curl_cffi import requests as curl_requests

            self._curl_session = curl_requests.Session(
                impersonate="chrome131",
                http_version=CurlHttpVersion.V1_1,
            )
            for name, value in self.cookies.cookies.items():
                self._curl_session.cookies.set(name, value)
            logger.info("Bayt transport: curl_cffi HTTP/1.1 (+ browser fallback)")
        except Exception as exc:  # noqa: BLE001
            self._curl_session = None
            logger.warning("curl_cffi unavailable (%s)", exc)

    def _headers(self, *, referer: str) -> dict[str, str]:
        return {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": referer or self.config.base_url,
            "User-Agent": self.settings.crawler_user_agent,
        }

    def fetch_listing_page(
        self,
        *,
        location: LocationDef,
        industry_key: str | None,
        page: int = 1,
    ) -> dict[str, Any]:
        url = self.config.listing_url(
            location=location, industry_key=industry_key, page=page
        )
        referer = self.config.listing_url(
            location=location, industry_key=industry_key, page=max(1, page - 1)
        )

        html: str | None = None
        try:
            html = self._curl_get_html(url, referer=referer)
            if self._looks_blocked(html):
                raise RuntimeError("Cloudflare / challenge page from curl")
            self.last_method = "curl"
        except Exception as curl_exc:  # noqa: BLE001
            logger.warning("Bayt curl blocked/failed (%s) — browser fallback", curl_exc)
            html = self._browser_get_html(url)
            self.last_method = "browser"

        if not html:
            raise RuntimeError(f"Bayt listing fetch returned empty HTML for {url}")

        rows = self.parse_listing_rows(html)
        total = self._parse_total(html)
        self._persist_cookies()
        return {
            "url": url,
            "positions": rows,
            "total_results": total,
            "page": page,
        }

    def parse_listing_rows(self, html: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for m in _LI_RE.finditer(html):
            parsed = self._parse_card(m.group("id"), m.group("body"))
            if parsed:
                rows.append(parsed)
        return rows

    def _parse_card(self, job_id: str, body: str) -> dict[str, Any] | None:
        tm = _TITLE_RE.search(body) or _TITLE_ALT_RE.search(body)
        if not tm:
            return None
        title = unescape(
            re.sub(r"\s+", " ", (tm.group("title_attr") or tm.group("title") or "")).strip()
        )
        if not title:
            return None
        href = tm.group("href").strip()
        company = ""
        cm = _COMPANY_RE.search(body)
        if cm:
            company = unescape(re.sub(r"\s+", " ", cm.group("company")).strip())
        location = ""
        lm = _LOCATION_RE.search(body)
        if lm:
            location = unescape(re.sub(r"\s+", " ", lm.group("city")).strip())
        salary = ""
        sm = _SALARY_RE.search(body)
        if sm:
            salary = unescape(re.sub(r"\s+", " ", sm.group("salary")).strip())
        posted_epoch = None
        em = _DATE_EPOCH_RE.search(body)
        if em:
            posted_epoch = em.group("epoch")
        posted_text = ""
        dm = _DATE_TEXT_RE.search(body)
        if dm:
            posted_text = re.sub(r"\s+", " ", dm.group("date")).strip()

        return {
            "id": str(job_id),
            "title": title,
            "company_name": company or "Unknown",
            "location": location,
            "link": urljoin(self.config.base_url + "/", href.lstrip("/")),
            "salary": salary,
            "posted_text": posted_text,
            "posted_epoch": posted_epoch,
        }

    def _parse_total(self, html: str) -> int | None:
        return largest_jobs_found_count(html, _TOTAL_RE, k_suffix_group=2)

    def _looks_blocked(self, html: str) -> bool:
        low = html.lower()
        if "attention required" in low and "cloudflare" in low:
            return True
        if "cf-browser-verification" in low or "just a moment" in low:
            return True
        if "data-job-id" not in html and "jobs found" not in low:
            return True
        return False

    def _curl_get_html(self, url: str, *, referer: str) -> str:
        if self._curl_session is None:
            raise RuntimeError("curl_cffi session not available")
        response = self._curl_session.get(
            url, headers=self._headers(referer=referer), timeout=35
        )
        if response.status_code >= 400:
            raise RuntimeError(f"HTTP {response.status_code}")
        return response.text or ""

    def _browser_get_html(self, url: str) -> str:
        from browsers.nodriver_fallback import NodriverSession
        from browsers.seleniumbase_fallback import seleniumbase_fetch

        # One Chrome instance reused for every fallback fetch in this crawl
        # (categories, pages, job-detail lookups) instead of relaunching per
        # request — same result, far fewer visible browser windows.
        if self._browser_session is None:
            self._browser_session = NodriverSession(guest=True)
        html = self._browser_session.fetch(url, wait_css="data-job-id", sleep=8)
        if html and not self._looks_blocked(html):
            return html

        logger.warning("nodriver guest failed/blocked — trying SeleniumBase UC")
        html = seleniumbase_fetch(url, guest=True)
        if not html:
            raise RuntimeError(
                "Browser fallback returned no HTML "
                "(guest Chrome / SeleniumBase both failed)"
            )
        if self._looks_blocked(html):
            raise RuntimeError(
                "Bayt still blocked after browser fetch (Cloudflare challenge?). "
                "Retry; if a CF checkbox appears, complete it once."
            )
        return html

    def _persist_cookies(self) -> None:
        if self._curl_session is None:
            return
        jar: dict[str, str] = {}
        try:
            for cookie in self._curl_session.cookies:
                name = getattr(cookie, "name", None) or cookie
                value = getattr(cookie, "value", None)
                if name and value is not None:
                    jar[str(name)] = str(value)
        except Exception:  # noqa: BLE001
            jar = {k: str(v) for k, v in dict(self._curl_session.cookies).items()}
        if jar:
            self.cookies.update(jar)

    def fetch_job_detail_html(self, url: str) -> str:
        """Job detail page — used to read exact PostedDate when listing is vague."""
        referer = self.config.base_url
        try:
            html = self._curl_get_html(url, referer=referer)
            if self._looks_blocked(html):
                raise RuntimeError("Cloudflare / challenge on Bayt job detail")
            self.last_method = "curl"
            self._persist_cookies()
            return html
        except Exception as curl_exc:  # noqa: BLE001
            logger.info("Bayt detail curl failed (%s) — browser fallback", curl_exc)
            html = self._browser_get_html(url)
            self.last_method = "browser"
            return html

    def close(self) -> None:
        if self._curl_session is not None:
            try:
                self._curl_session.close()
            except Exception:  # noqa: BLE001
                pass
        if self._browser_session is not None:
            self._browser_session.close()
            self._browser_session = None
