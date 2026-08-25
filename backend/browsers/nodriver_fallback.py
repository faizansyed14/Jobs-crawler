from __future__ import annotations

import asyncio
import json
import logging
import tempfile
from typing import Any, Optional

logger = logging.getLogger(__name__)


def _guest_browser_args() -> list[str]:
    return [
        "--guest",
        "--disable-sync",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-features=ChromeWhatsNewUI,AccountConsistency,DialMediaRouteProvider",
    ]


def nodriver_fetch(
    url: str,
    user_data_dir: str | None = None,
    *,
    wait_css: str | None = None,
    sleep: float = 4,
    guest: bool = False,
) -> Optional[str]:
    """Fetch page HTML with headed Chrome (CDP).

    guest=True → Chrome Guest session (no Google account picker).
    """
    try:
        import nodriver as uc
    except ImportError:
        logger.warning("nodriver not installed")
        return None

    async def _run() -> str:
        kwargs: dict[str, Any] = {"headless": False}
        if guest:
            # Fresh temp profile + --guest avoids profile/account chooser.
            kwargs["user_data_dir"] = tempfile.mkdtemp(prefix="nd-guest-")
            kwargs["browser_args"] = _guest_browser_args()
            logger.info("nodriver guest session → %s", url[:120])
        elif user_data_dir:
            kwargs["user_data_dir"] = user_data_dir

        browser = await uc.start(**kwargs)
        try:
            page = await browser.get(url)
            await page.sleep(sleep)
            if wait_css:
                for _ in range(16):
                    html = await page.get_content()
                    needle = wait_css.strip("[]#.")
                    if needle and needle in html:
                        break
                    if "data-job-id" in html:
                        break
                    if "Attention Required" in html or "Just a moment" in html:
                        # CF interstitial — give user time if visible
                        await page.sleep(2.0)
                        continue
                    await page.sleep(1.5)
            html = await page.get_content()
            if not html or len(html) < 200:
                raise RuntimeError("Empty HTML from Chrome guest session")
            return html
        finally:
            try:
                browser.stop()
            except Exception:  # noqa: BLE001
                pass

    try:
        return asyncio.run(_run())
    except Exception as exc:  # noqa: BLE001
        logger.exception("nodriver HTML fetch failed: %s", exc)
        return None


class NodriverSession:
    """One headed Chrome instance reused across many fetches.

    A fresh `uc.start()` launches a whole new Chrome process — fine for a
    single one-off fetch, wasteful (and visibly annoying) when a crawl needs
    the browser fallback repeatedly (e.g. once per Bayt category). This
    keeps one browser + one event loop alive for the caller's lifetime;
    call `close()` when the crawl is done.
    """

    def __init__(self, *, guest: bool = True) -> None:
        self._guest = guest
        self._loop: asyncio.AbstractEventLoop | None = None
        self._browser: Any = None

    def _ensure_browser(self) -> Any:
        if self._browser is not None:
            return self._browser
        try:
            import nodriver as uc
        except ImportError:
            logger.warning("nodriver not installed")
            return None

        if self._loop is None:
            self._loop = asyncio.new_event_loop()

        kwargs: dict[str, Any] = {"headless": False}
        if self._guest:
            kwargs["user_data_dir"] = tempfile.mkdtemp(prefix="nd-guest-")
            kwargs["browser_args"] = _guest_browser_args()

        async def _start() -> Any:
            return await uc.start(**kwargs)

        logger.info("nodriver session starting (reused across this crawl)")
        self._browser = self._loop.run_until_complete(_start())
        return self._browser

    def fetch(
        self, url: str, *, wait_css: str | None = None, sleep: float = 4
    ) -> Optional[str]:
        browser = self._ensure_browser()
        if browser is None or self._loop is None:
            return None

        async def _get() -> str:
            page = await browser.get(url)
            await page.sleep(sleep)
            if wait_css:
                needle = wait_css.strip("[]#.")
                for _ in range(16):
                    html = await page.get_content()
                    if needle and needle in html:
                        break
                    if "Attention Required" in html or "Just a moment" in html:
                        await page.sleep(2.0)
                        continue
                    await page.sleep(1.5)
            html = await page.get_content()
            if not html or len(html) < 200:
                raise RuntimeError("Empty HTML from reused Chrome session")
            return html

        try:
            return self._loop.run_until_complete(_get())
        except Exception as exc:  # noqa: BLE001
            logger.exception("nodriver reused-session fetch failed: %s", exc)
            # Session may be wedged (crashed tab/CF loop) — drop it so the
            # next fetch() call starts a clean browser instead of hanging.
            self.close()
            return None

    def close(self) -> None:
        if self._browser is not None:
            try:
                self._browser.stop()
            except Exception:  # noqa: BLE001
                pass
            self._browser = None
        if self._loop is not None:
            try:
                self._loop.close()
            except Exception:  # noqa: BLE001
                pass
            self._loop = None


def nodriver_fetch_json(
    *,
    page_url: str,
    api_url: str,
    headers: dict[str, str],
    user_data_dir: str,
) -> Optional[dict[str, Any]]:
    """Open listing page, then call search API via in-page XHR (bypasses Akamai TLS issues)."""
    try:
        import nodriver as uc
    except ImportError:
        logger.warning("nodriver not installed")
        return None

    headers_json = json.dumps(headers)
    api_json = json.dumps(api_url)

    script = f"""
    (() => {{
      const headers = {headers_json};
      const apiUrl = {api_json};
      return new Promise((resolve) => {{
        const xhr = new XMLHttpRequest();
        xhr.open("GET", apiUrl, true);
        xhr.withCredentials = true;
        Object.entries(headers).forEach(([k, v]) => {{
          try {{ xhr.setRequestHeader(k, String(v)); }} catch (e) {{}}
        }});
        xhr.onload = () => resolve({{ status: xhr.status, body: xhr.responseText }});
        xhr.onerror = () => resolve({{ status: 0, body: "network_error" }});
        xhr.ontimeout = () => resolve({{ status: 0, body: "timeout" }});
        xhr.timeout = 30000;
        xhr.send();
      }});
    }})()
    """

    async def _run() -> dict[str, Any]:
        browser = await uc.start(
            headless=False,
            user_data_dir=tempfile.mkdtemp(prefix="nd-xhr-"),
            browser_args=_guest_browser_args(),
        )
        try:
            page = await browser.get(page_url)
            await page.sleep(5)
            raw = await page.evaluate(script)
            if isinstance(raw, str):
                raw = json.loads(raw)
            if not isinstance(raw, dict):
                raise RuntimeError(f"Unexpected evaluate result: {type(raw)}")
            status = raw.get("status")
            body = raw.get("body") or ""
            if status != 200:
                raise RuntimeError(f"Browser XHR HTTP {status}: {str(body)[:200]}")
            data = json.loads(body)
            if not isinstance(data, dict):
                raise RuntimeError("Browser XHR did not return a JSON object")
            return data
        finally:
            try:
                browser.stop()
            except Exception:  # noqa: BLE001
                pass

    try:
        logger.info("Browser XHR fallback → %s", api_url[:120])
        return asyncio.run(_run())
    except Exception as exc:  # noqa: BLE001
        logger.exception("nodriver JSON fetch failed: %s", exc)
        return None
