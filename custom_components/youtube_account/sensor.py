"""Sensors of the YouTube account: home feed and Watch Later."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import YouTubeAccountConfigEntry
from .coordinator import YouTubeAccountCoordinator, YouTubeAccountEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: YouTubeAccountConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the sensors."""
    async_add_entities(
        [
            YouTubeHomeFeedSensor(entry.runtime_data),
            YouTubeWatchLaterSensor(entry.runtime_data),
        ]
    )


class YouTubeHomeFeedSensor(YouTubeAccountEntity, SensorEntity):
    """The home feed: the number of items, and the items as an attribute.

    Read when asked (the Refresh button, the refresh_feed action, opening the
    media browser or the card), never on a timer.
    """

    _attr_translation_key = "home_feed"
    # The item list changes on every read; the recorder only needs the count.
    _unrecorded_attributes = frozenset({"items"})

    def __init__(self, coordinator: YouTubeAccountCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "home_feed")

    @property
    def native_value(self) -> int:
        """Return how many items the feed has."""
        return len(self.coordinator.data.items)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the items and when they were read."""
        data = self.coordinator.data
        return {
            "items": [item.as_dict() for item in data.items],
            "updated_at": data.updated_at.isoformat() if data.updated_at else None,
            "shorts_hidden": data.shorts_hidden,
            # The Configure option, so the feed card can say how often it reads.
            "min_refresh_minutes": round(
                self.coordinator.min_refresh.total_seconds() / 60
            ),
        }


class YouTubeWatchLaterSensor(YouTubeAccountEntity, SensorEntity):
    """Watch Later: the number of videos, and each with its watched percent.

    Read with the home feed. Unknown until the first read works.
    """

    _attr_translation_key = "watch_later"
    _unrecorded_attributes = frozenset({"items"})

    def __init__(self, coordinator: YouTubeAccountCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "watch_later")

    @property
    def native_value(self) -> int | None:
        """Return how many videos Watch Later has."""
        items = self.coordinator.data.watch_later
        return None if items is None else len(items)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the videos, in list order."""
        items = self.coordinator.data.watch_later or ()
        return {"items": [item.as_dict() for item in items]}
