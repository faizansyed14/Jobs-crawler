from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlencode

from config.portals import NaukrigulfConfig
from config.settings import get_settings
from core.session_manager import CookieJar

logger = logging.getLogger(__name__)


class NaukrigulfAPIClient:
    """Naukrigulf `/spapi/jobapi/search` client.

    1) curl_cffi HTTP/1.1 + warmup (fast path)
    2) Real Chrome via nodriver XHR if curl times out / is reset
    """

    def __init__(self, config: NaukrigulfConfig | None = None) -> None:
        self.config = config or NaukrigulfConfig()
        self.settings = get_settings()
        self.cookies = CookieJar(self.config.name)
        self._curl_session = None
        self._warmed = False
        self.last_method = "api"
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
            logger.info("Naukrigulf transport: curl_cffi HTTP/1.1")
        except Exception as exc:  # noqa: BLE001
            self._curl_session = None
            logger.warning("curl_cffi unavailable (%s)", exc)

    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "Accept-Format": "strict",
            "Accept-Language": "ENGLISH",
            "Content-Type": "application/json",
            "Device-Type": "desktop",
            "appId": self.config.app_id,
            "systemId": self.config.system_id,
            "clientId": "desktop",
            "client-type": "desktop",
            "cache-control": "no-cache",
            "locationId": "",
            "puppeteer": "false",
            "userData": "|AE",
            "version": "v1",
        }

    def warmup(self, location: str = "dubai") -> None:
        if self._warmed or self._curl_session is None:
            return
        warm_url = f"{self.config.base_url}/jobs-in-{location}"
        try:
            self._curl_session.get(warm_url, timeout=20)
            self._warmed = True
            self._persist_cookies()
            logger.info("Session warmed via %s", warm_url)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Warmup failed (%s)", exc)
            self._warmed = False

    def search_jobs(
        self,
        *,
        location: str,
        freshness_days: int | None = None,
        page: int = 1,
        limit: int | None = None,
        cluster_ind: str | None = None,
        sort_by_date: bool = True,
    ) -> dict[str, Any]:
        limit = limit or self.config.default_limit
        offset = (page - 1) * limit
        params: dict[str, Any] = {
            "Experience": "",
            "Keywords": "",
            "KeywordsAr": "",
            "Limit": limit,
            "Location": location,
            "LocationAr": "",
            "Offset": offset,
            "SortPreference": self.config.sort_preference_date if sort_by_date else "",
            "breadcrumb": 1,
            "clusterSelected": 1,
            "pageNo": page,
            "seo": 1,
            "showBellyFilters": "true",
            "showSponsoredJobs": "true",
            "topEmployer": "true",
        }
        if freshness_days is not None:
            params["Freshness"] = freshness_days
        if cluster_ind:
            params["ClusterInd"] = cluster_ind
            params["xz"] = "1_2_5"

        api_url = f"{self.config.search_url}?{urlencode(params)}"
        referer = f"{self.config.base_url}/jobs-in-{location}"

        # Fast path
        try:
            self.warmup(location=location)
            data = self._curl_get_json(api_url)
            self.last_method = "api"
            self._persist_cookies()
            return data
        except Exception as curl_exc:  # noqa: BLE001
            logger.warning("curl API failed (%s) — trying browser XHR", curl_exc)

        data = self._browser_get_json(api_url=api_url, referer=referer)
        self.last_method = "browser"
        return data

    def _curl_get_json(self, url: str) -> dict[str, Any]:
        if self._curl_session is None:
            raise RuntimeError("curl_cffi session not available")

        headers = self._headers()
        headers["Referer"] = f"{self.config.base_url}/jobs-in-dubai"
        last_error: Exception | None = None

        for attempt in range(2):
            try:
                response = self._curl_session.get(url, headers=headers, timeout=20)
                if response.status_code >= 400:
                    raise RuntimeError(
                        f"HTTP {response.status_code}: {response.text[:200]}"
                    )
                data = response.json()
                if isinstance(data, dict) and data.get("statusCode") == 400:
                    raise RuntimeError(data.get("message") or "API validation error")
                return data
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                logger.warning("curl attempt %s failed: %s", attempt + 1, exc)
                self._warmed = False
                self._init_transport()
                self.warmup()

        assert last_error is not None
        raise last_error

    def _browser_get_json(self, *, api_url: str, referer: str) -> dict[str, Any]:
        from browsers.nodriver_fallback import nodriver_fetch_json

        profile = str(Path(self.settings.browser_profile_dir) / "naukrigulf")
        Path(profile).mkdir(parents=True, exist_ok=True)
        payload = nodriver_fetch_json(
            page_url=referer,
            api_url=api_url,
            headers=self._headers(),
            user_data_dir=profile,
        )
        if not payload:
            raise RuntimeError("Browser XHR fallback returned no data")
        if isinstance(payload, dict) and payload.get("statusCode") == 400:
            raise RuntimeError(payload.get("message") or "API validation error")
        return payload

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
