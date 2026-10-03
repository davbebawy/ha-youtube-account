"""Binary sensor of the YouTube account: signed in."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.const import EntityCategory
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
    """Set up the binary sensor."""
    async_add_entities([YouTubeSignedInSensor(entry.runtime_data)])


class YouTubeSignedInSensor(YouTubeAccountEntity, BinarySensorEntity):
    """Off once YouTube stops accepting the account's cookies."""

    _attr_translation_key = "signed_in"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: YouTubeAccountCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "signed_in")

    @property
    def available(self) -> bool:
        """Stay available: being signed out is what this reports."""
        return True

    @property
    def is_on(self) -> bool:
        """Return True while the account is signed in."""
        return self.coordinator.signed_in
