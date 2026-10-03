"""Diagnostics for YouTube Account."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import YouTubeAccountConfigEntry
from .const import CONF_COOKIES

# The cookies are a signed-in Google session.
TO_REDACT = {CONF_COOKIES, "unique_id"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: YouTubeAccountConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for the account."""
    account = entry.runtime_data
    data = account.data
    return {
        "entry": async_redact_data(entry.as_dict(), TO_REDACT),
        "signed_in": account.signed_in,
        "feed_items": len(data.items) if data else None,
        "feed_updated_at": data.updated_at if data else None,
        "watch_later_items": len(data.watch_later)
        if data and data.watch_later is not None
        else None,
        "last_update_success": account.last_update_success,
    }
