"""Browser fallbacks used only when the JSON API path fails."""

from browsers.camoufox_fallback import camoufox_fetch
from browsers.nodriver_fallback import NodriverSession, nodriver_fetch
from browsers.seleniumbase_fallback import seleniumbase_fetch

__all__ = ["nodriver_fetch", "NodriverSession", "seleniumbase_fetch", "camoufox_fetch"]