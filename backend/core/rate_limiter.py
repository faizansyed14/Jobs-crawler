from __future__ import annotations

import logging
import random
import time
from typing import Callable

from config.settings import get_settings

logger = logging.getLogger(__name__)


class AdaptiveRateLimiter:
    """Sequential polite pacing: base delay + jitter + backoff on 429/503."""

    def __init__(
        self,
        base_delay: float | None = None,
        max_delay: float | None = None,
    ) -> None:
        settings = get_settings()
        self.base_delay = (
            base_delay if base_delay is not None else settings.min_delay_seconds
        )
        self.max_delay = (
            max_delay if max_delay is not None else settings.max_delay_seconds
        )
        self.location_gap = settings.location_gap_seconds
        self.delay = float(self.base_delay)

    def on_success(self) -> None:
        self.delay = max(self.base_delay, self.delay * 0.95)

    def on_rate_limit(self) -> None:
        self.delay = min(self.max_delay, self.delay * 2)
        logger.warning("Rate limited — delay now %.1fs", self.delay)

    def wait(
        self,
        *,
        reason: str = "page",
        on_tick: Callable[[float, float], None] | None = None,
    ) -> float:
        """Sleep with jitter. Optionally tick remaining seconds for UI."""
        jitter = random.uniform(0.5, 4.0)
        sleep_for = min(self.max_delay, self.delay + jitter)
        logger.info("Polite wait %.1fs (%s)", sleep_for, reason)
        remaining = sleep_for
        step = 0.5
        while remaining > 0:
            if on_tick:
                on_tick(remaining, sleep_for)
            chunk = min(step, remaining)
            time.sleep(chunk)
            remaining -= chunk
        return sleep_for

    def wait_between_locations(
        self,
        on_tick: Callable[[float, float], None] | None = None,
    ) -> float:
        sleep_for = float(self.location_gap)
        logger.info("Location gap wait %.1fs", sleep_for)
        remaining = sleep_for
        step = 0.5
        while remaining > 0:
            if on_tick:
                on_tick(remaining, sleep_for)
            chunk = min(step, remaining)
            time.sleep(chunk)
            remaining -= chunk
        return sleep_for
