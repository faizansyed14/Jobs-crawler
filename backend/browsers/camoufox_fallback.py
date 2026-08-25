from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def camoufox_fetch(url: str) -> Optional[str]:
    """TERTIARY fallback — Camoufox (free Firefox engine)."""
    try:
        import asyncio
        from camoufox.async_api import AsyncCamoufox
    except ImportError:
        logger.warning("camoufox not installed")
        return None

    async def _run() -> str:
        async with AsyncCamoufox(headless=False) as browser:
            page = await browser.new_page()
            await page.goto(url, wait_until="networkidle")
            return await page.content()

    try:
        return asyncio.run(_run())
    except Exception as exc:  # noqa: BLE001
        logger.exception("camoufox fetch failed: %s", exc)
        return None