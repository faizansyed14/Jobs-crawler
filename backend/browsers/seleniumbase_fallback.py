from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def seleniumbase_fetch(
    url: str,
    user_data_dir: str | None = None,
    *,
    guest: bool = False,
) -> Optional[str]:
    """SECONDARY fallback — SeleniumBase UC for challenge pages."""
    try:
        from seleniumbase import SB
    except ImportError:
        logger.warning("seleniumbase not installed")
        return None

    try:
        kwargs: dict = {"uc": True, "test": True, "headless": False}
        if guest or not user_data_dir:
            kwargs["guest_mode"] = True
        else:
            kwargs["user_data_dir"] = user_data_dir
        with SB(**kwargs) as sb:
            sb.uc_open_with_reconnect(url, reconnect_time=6)
            sb.sleep(3)
            return sb.get_page_source()
    except TypeError:
        # Older seleniumbase without guest_mode kwarg
        try:
            with SB(uc=True, test=True, headless=False) as sb:
                sb.uc_open_with_reconnect(url, reconnect_time=6)
                sb.sleep(3)
                return sb.get_page_source()
        except Exception as exc:  # noqa: BLE001
            logger.exception("seleniumbase fetch failed: %s", exc)
            return None
    except Exception as exc:  # noqa: BLE001
        logger.exception("seleniumbase fetch failed: %s", exc)
        return None
