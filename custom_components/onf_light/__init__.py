"""The ONF Light integration."""
from __future__ import annotations

from homeassistant.const import CONF_ADDRESS, Platform
from homeassistant.core import HomeAssistant

from .ble_client import ONFLightBLEClient
from .const import (
    CONF_DEVICE_TYPE,
    CONF_IDLE_DISCONNECT,
    CONF_MODEL,
    CONF_TIMERS,
    IDLE_DISCONNECT_SECONDS,
    resolve_device_type,
)
from .coordinator import ONFLightDiagnosticCoordinator
from .data import ONFLightConfigEntry, ONFLightData
from .helpers import relabel_timer_kelvin

PLATFORMS: list[Platform] = [Platform.LIGHT, Platform.BUTTON, Platform.SENSOR, Platform.BINARY_SENSOR]


def _relabel_stored_timers(hass: HomeAssistant, entry: ONFLightConfigEntry) -> None:
    """Bring stored timer Kelvin labels in line with the app's scale for the model.

    The device value (cct_internal) is kept, so the light keeps doing exactly
    what it did; only the Kelvin shown in HA changes (blue-white models).
    """
    timers = entry.options.get(CONF_TIMERS)
    if not timers:
        return
    device_type = entry.data.get(CONF_DEVICE_TYPE)
    if device_type is None:
        device_type = resolve_device_type(entry.data.get(CONF_MODEL, entry.title))
    relabelled = relabel_timer_kelvin(timers, device_type)
    if relabelled is not None:
        hass.config_entries.async_update_entry(
            entry, options={**entry.options, CONF_TIMERS: relabelled}
        )


async def async_setup_entry(hass: HomeAssistant, entry: ONFLightConfigEntry) -> bool:
    """Set up ONF Light from a config entry."""
    _relabel_stored_timers(hass, entry)
    address = entry.data[CONF_ADDRESS]
    idle_seconds = float(entry.options.get(CONF_IDLE_DISCONNECT, IDLE_DISCONNECT_SECONDS))
    client = ONFLightBLEClient(hass, address, idle_disconnect_seconds=idle_seconds)
    coordinator = ONFLightDiagnosticCoordinator(hass, entry, client)
    entry.runtime_data = ONFLightData(client=client, coordinator=coordinator)
    # Only reads in-memory data, so it never fails; avoids empty sensors at startup.
    await coordinator.async_config_entry_first_refresh()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ONFLightConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await entry.runtime_data.client.disconnect()
    return unload_ok
