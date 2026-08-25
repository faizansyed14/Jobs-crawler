from __future__ import annotations

import logging
import re
from html import unescape
from typing import Any
from urllib.parse import urljoin

from config.portals import GulfTalentConfig, LocationDef
from config.settings import get_settings
from core.session_manager import CookieJar

logger = logging.getLogger(__name__)

_ROW_RE = re.compile(
    r'<tr class="content-visibility-auto">(.*?)</tr>',
    flags=re.I | re.S,
)
_JOB_LINK_RE = re.compile(
    r'data-ga-label="(?P<id>\d+)"[^>]*href="(?P<href>/[^"]+/jobs/[^"]+[-_]\d+)"[^>]*>'
    r"\s*(?P<title>[^<]+?)\s*</a>",
    flags=re.I | re.S,
)
# Fallback if attribute order differs
_JOB_LINK_ALT_RE = re.compile(
    r'href="(?P<href>/[^"]+/jobs/[^"]+[-_](?P<id>\d+))"\s*>\s*(?P<title>[^<]+?)\s*</a>',
    flags=re.I | re.S,
)
_COMPANY_RE = re.compile(
    r'href="/companies/[^"]+"[^>]*>\s*(?P<company>[^<]+?)\s*</a>',
    flags=re.I | re.S,
)
# Confidential / unlinked employers: plain text after title </p> … </td>
_COMPANY_PLAIN_RE = re.compile(
    r"</p>\s*(?P<company>[^<]{2,120}?)\s*</td>",
    flags=re.I | re.S,
)
_COMPANY_LOGO_RE = re.compile(
    r'(?:alt|title)="(?P<company>[^"]+?)\s+careers(?:\s*&\s*jobs)?"',
    flags=re.I,
)
_LOCATION_RE = re.compile(
    r'<span title="(?P<title>[^"]*)">\s*(?P<text>[^<]+?)\s*</span>',
    flags=re.I | re.S,
)
_DATE_CELL_RE = re.compile(
    r'<td class="col-sm-4">\s*(?P<date>[^<]+?)\s*</td>',
    flags=re.I | re.S,
)
_TOTAL_RE = re.compile(r"(\d[\d,]*)\s+Jobs found", flags=re.I)


class GulfTalentAPIClient:
    """GulfTalent HTML listing client (curl_cffi + session warmup).

    Mirrors NaukrigulfAPIClient transport pattern, but listings come from SSR
    category/industry pages — `/api/jobs/search` does not honor filters.
    """

    def __init__(self, config: GulfTalentConfig | None = None) -> None:
        self.config = config or GulfTalentConfig()
        self.settings = get_settings()
        self.cookies = CookieJar(self.config.name)
        self._curl_session = None
        self._warmed = False
        self.last_method = "html"
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
            logger.info("GulfTalent transport: curl_cffi HTTP/1.1")
        except Exception as exc:  # noqa: BLE001
            self._curl_session = None
            logger.warning("curl_cffi unavailable (%s)", exc)

    def _headers(self, *, referer: str) -> dict[str, str]:
        return {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": referer,
        }

    def warmup(self, location: LocationDef, industry_key: str | None = None) -> None:
        if self._warmed or self._curl_session is None:
            return
        warm_url = self.config.listing_url(
            location=location, industry_key=industry_key, page=1
        )
        try:
            self._curl_session.get(warm_url, timeout=25)
            self._warmed = True
            self._persist_cookies()
            logger.info("GulfTalent session warmed via %s", warm_url)
        except Exception as exc:  # noqa: BLE001
            logger.warning("GulfTalent warmup failed (%s)", exc)
            self._warmed = False

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
        self.warmup(location, industry_key)
        html = self._curl_get_html(url, referer=referer)
        self.last_method = "html"
        self._persist_cookies()
        rows = self.parse_listing_rows(html)
        total = None
        m = _TOTAL_RE.search(html)
        if m:
            total = int(m.group(1).replace(",", ""))
        return {
            "url": url,
            "positions": rows,
            "total_results": total,
            "page": page,
        }

    def parse_listing_rows(self, html: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for row_html in _ROW_RE.findall(html):
            parsed = self._parse_row(row_html)
            if parsed:
                rows.append(parsed)
        return rows

    def _parse_row(self, row_html: str) -> dict[str, Any] | None:
        m = _JOB_LINK_RE.search(row_html)
        if not m:
            m = _JOB_LINK_ALT_RE.search(row_html)
        if not m:
            return None

        job_id = m.group("id").strip()
        href = m.group("href").strip()
        title = unescape(re.sub(r"\s+", " ", m.group("title")).strip())
        company = self._extract_company(row_html)
        location = ""
        lm = _LOCATION_RE.search(row_html)
        if lm:
            location = (lm.group("title") or lm.group("text") or "").strip()
            location = unescape(re.sub(r"\s+", " ", location))
        posted_text = ""
        dm = _DATE_CELL_RE.search(row_html)
        if dm:
            posted_text = re.sub(r"\s+", " ", dm.group("date")).strip()

        return {
            "id": job_id,
            "title": title,
            "company_name": company,
            "location": location,
            "link": urljoin(self.config.base_url + "/", href.lstrip("/")),
            "posted_text": posted_text,
        }

    def _extract_company(self, row_html: str) -> str:
        cm = _COMPANY_RE.search(row_html)
        if cm:
            name = unescape(re.sub(r"\s+", " ", cm.group("company")).strip())
            if name:
                return name
        # Unlinked employer name (common on GulfTalent when no company profile URL)
        pm = _COMPANY_PLAIN_RE.search(row_html)
        if pm:
            name = unescape(re.sub(r"\s+", " ", pm.group("company")).strip())
            # Ignore leftover markup crumbs / empty
            if name and "<" not in name and len(name) >= 2:
                return name
        lm = _COMPANY_LOGO_RE.search(row_html)
        if lm:
            name = unescape(re.sub(r"\s+", " ", lm.group("company")).strip())
            if name:
                return name
        return ""

    def _curl_get_html(self, url: str, *, referer: str) -> str:
        if self._curl_session is None:
            raise RuntimeError("curl_cffi session not available")

        headers = self._headers(referer=referer)
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                response = self._curl_session.get(url, headers=headers, timeout=30)
                if response.status_code >= 400:
                    raise RuntimeError(
                        f"HTTP {response.status_code}: {response.text[:200]}"
                    )
                text = response.text or ""
                if "content-visibility-auto" not in text and "Jobs found" not in text:
                    raise RuntimeError("Unexpected GulfTalent listing HTML")
                return text
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                logger.warning("GulfTalent curl attempt %s failed: %s", attempt + 1, exc)
                self._warmed = False
                self._init_transport()
                # retry without requiring prior warm success
                try:
                    if self._curl_session is not None:
                        self._curl_session.get(url, timeout=25)
                        self._warmed = True
                except Exception:  # noqa: BLE001
                    pass

        assert last_error is not None
        raise last_error

    def fetch_job_detail_html(self, url: str) -> str:
        """Job detail page — JSON-LD datePosted when listing only shows '21 Aug'."""
        referer = self.config.base_url
        html = self._curl_get_html(url, referer=referer)
        self.last_method = "html"
        self._persist_cookies()
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

    def close(self) -> None:
        if self._curl_session is not None:
            try:
                self._curl_session.close()
            except Exception:  # noqa: BLE001
                pass
