"""Button platform for ONF Light integration."""
from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .data import ONFLightConfigEntry
from .entity import device_info_for_entry

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ONFLightConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up ONF Light button from a config entry."""
    async_add_entities([ONFLightSyncTimeButton(entry)])


class ONFLightSyncTimeButton(ButtonEntity):
    """Button that syncs the device RTC to current local time."""

    _attr_has_entity_name = True
    _attr_translation_key = "sync_time"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:timer-sync"

    def __init__(self, entry: ONFLightConfigEntry) -> None:
        """Initialize the sync time button."""
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_sync_time"
        self._attr_device_info = device_info_for_entry(entry)

    async def async_press(self) -> None:
        """Sync the device RTC to current local time."""
        if not await self._entry.runtime_data.client.sync_time():
            raise HomeAssistantError(
                f"Could not sync the clock of {self._entry.title}; the light is not reachable."
            )
        _LOGGER.debug("Manual time sync for %s: ok", self._entry.title)
