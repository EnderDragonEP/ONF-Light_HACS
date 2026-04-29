"""Button platform for ONF Light integration."""
from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
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

    def __init__(self, entry: ConfigEntry) -> None:
        """Initialize the sync time button."""
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_sync_time"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.data[CONF_ADDRESS])},
        )

    async def async_press(self) -> None:
        """Sync the device RTC to current local time."""
        client = self.hass.data.get(DOMAIN, {}).get(self._entry.entry_id, {}).get("client")
        if client is None:
            _LOGGER.warning("No BLE client available for time sync on %s", self._entry.title)
            return
        success = await client.sync_time()
        _LOGGER.debug(
            "Manual time sync for %s: %s",
            self._entry.title,
            "ok" if success else "failed",
        )
