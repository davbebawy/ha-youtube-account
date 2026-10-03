"""The YouTube Account integration: home feed, Watch Later and the feed card.

It plays nothing itself. Playback goes through Home Assistant, as
media_player.play_media on a YouTube on TV player.
"""

from __future__ import annotations

from pathlib import Path

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType
from homeassistant.loader import async_get_integration

from .const import DOMAIN
from .coordinator import YouTubeAccountCoordinator, cache_store
from .services import async_setup_services

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.SENSOR,
]

# The feed card ships with the integration; Home Assistant loads it on every
# dashboard, so there's no resource to add by hand.
CARD_URL = f"/{DOMAIN}/youtube-feed-card.js"
CARD_PATH = Path(__file__).parent / "frontend" / "youtube-feed-card.js"

type YouTubeAccountConfigEntry = ConfigEntry[YouTubeAccountCoordinator]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the actions and the feed card."""
    async_setup_services(hass)
    await _async_register_card(hass)
    return True


async def _async_register_card(hass: HomeAssistant) -> None:
    """Serve the feed card and load it on every dashboard."""
    # Imported here: tests run without the frontend.
    from homeassistant.components.frontend import (  # noqa: PLC0415
        DATA_EXTRA_MODULE_URL,
        add_extra_js_url,
    )
    from homeassistant.components.http import StaticPathConfig  # noqa: PLC0415

    if hass.http is None or DATA_EXTRA_MODULE_URL not in hass.data:
        return
    await hass.http.async_register_static_paths(
        [StaticPathConfig(CARD_URL, str(CARD_PATH), cache_headers=False)]
    )
    # The version in the URL makes browsers fetch the card again after an update.
    integration = await async_get_integration(hass, DOMAIN)
    add_extra_js_url(hass, f"{CARD_URL}?v={integration.version}")


async def async_setup_entry(
    hass: HomeAssistant, entry: YouTubeAccountConfigEntry
) -> bool:
    """Set up the account from a config entry."""
    account = YouTubeAccountCoordinator(hass, entry)
    if not await account.async_load_cache():
        await account.async_config_entry_first_refresh()
    entry.runtime_data = account
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Delete the feed cache with the account."""
    await cache_store(hass, entry.entry_id).async_remove()


async def async_unload_entry(
    hass: HomeAssistant, entry: YouTubeAccountConfigEntry
) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
