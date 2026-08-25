from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from config.settings import get_settings

logger = logging.getLogger(__name__)


class CookieJar:
    """Persist cookies between runs for session continuity."""

    def __init__(self, portal_name: str, cookie_dir: Path | None = None) -> None:
        settings = get_settings()
        directory = cookie_dir or settings.cookie_dir
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / f"{portal_name}.json"
        self._cookies: dict[str, str] = {}
        self.load()

    def load(self) -> dict[str, str]:
        if not self.path.exists():
            self._cookies = {}
            return self._cookies
        try:
            self._cookies = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed reading cookies %s: %s", self.path, exc)
            self._cookies = {}
        return self._cookies

    def save(self, cookies: dict[str, Any] | None = None) -> None:
        if cookies is not None:
            self._cookies = {str(k): str(v) for k, v in cookies.items()}
        self.path.write_text(json.dumps(self._cookies, indent=2), encoding="utf-8")

    def update(self, cookies: dict[str, Any]) -> None:
        for key, value in cookies.items():
            self._cookies[str(key)] = str(value)
        self.save()

    @property
    def cookies(self) -> dict[str, str]:
        return dict(self._cookies)