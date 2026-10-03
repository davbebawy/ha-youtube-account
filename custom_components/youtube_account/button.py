"""Button of the YouTube account: refresh the home feed."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import YouTubeAccountConfigEntry
from .coordinator import YouTubeAccountCoordinator, YouTubeAccountEntity

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: YouTubeAccountConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the button."""
    async_add_entities([YouTubeRefreshFeedButton(entry.runtime_data)])


class YouTubeRefreshFeedButton(YouTubeAccountEntity, ButtonEntity):
    """Reads the home feed again."""

    _attr_translation_key = "refresh_feed"

    def __init__(self, coordinator: YouTubeAccountCoordinator) -> None:
        """Initialize the button."""
        super().__init__(coordinator, "refresh_feed")

    @property
    def available(self) -> bool:
        """Stay available, so a failed read can be tried again."""
        return True

    async def async_press(self) -> None:
        """Read the feed."""
        await self.coordinator.async_request_refresh()
