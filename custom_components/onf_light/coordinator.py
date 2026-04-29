"""DataUpdateCoordinator for ONF Light diagnostic data."""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.components.bluetooth import async_last_service_info
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .ble_client import ONFLightBLEClient
from .const import (
    CONF_DEVICE_TYPE,
    CONF_TIMERS,
    DOMAIN,
    is_brightness_only,
    kelvin_range_for_type,
)

_LOGGER = logging.getLogger(__name__)

DIAGNOSTIC_UPDATE_INTERVAL = timedelta(seconds=30)


class ONFLightDiagnosticCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Polls and aggregates diagnostic data for one ONF Light device."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: ONFLightBLEClient,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=f"ONF Light {entry.title}",
            update_interval=DIAGNOSTIC_UPDATE_INTERVAL,
        )
        self._entry = entry
        self._client = client

    async def _async_update_data(self) -> dict[str, Any]:
        """Aggregate diagnostic snapshot from in-memory sources (never raises)."""
        address: str = self._entry.data.get("address", "")
        service_info = async_last_service_info(self.hass, address, connectable=True)
        entry_store = self.hass.data.get(DOMAIN, {}).get(self._entry.entry_id, {})
        diag: dict[str, Any] = entry_store.get("diagnostics", {})
        timers: list[dict] = self._entry.options.get(CONF_TIMERS, [])
        device_type = self._entry.data.get(CONF_DEVICE_TYPE)

        return {
            "is_connected": self._client.is_connected,
            "rssi": service_info.rssi if service_info else None,
            "firmware_version": diag.get("firmware_version"),
            "active_timer_count": sum(1 for t in timers if t.get("active")),
            "timers": timers,
            "kelvin_range": kelvin_range_for_type(device_type),
            "brightness_only": is_brightness_only(device_type),
        }
