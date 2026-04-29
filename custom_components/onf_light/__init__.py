"""The ONF Light integration."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, Platform
from homeassistant.core import HomeAssistant

from .ble_client import ONFLightBLEClient
from .const import CONF_IDLE_DISCONNECT, DOMAIN, IDLE_DISCONNECT_SECONDS
from .coordinator import ONFLightDiagnosticCoordinator

PLATFORMS: list[Platform] = [Platform.LIGHT, Platform.BUTTON, Platform.SENSOR, Platform.BINARY_SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up ONF Light from a config entry."""
    address = entry.data[CONF_ADDRESS]
    idle_seconds = float(entry.options.get(CONF_IDLE_DISCONNECT, IDLE_DISCONNECT_SECONDS))
    client = ONFLightBLEClient(hass, address, idle_disconnect_seconds=idle_seconds)
    coordinator = ONFLightDiagnosticCoordinator(hass, entry, client)
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "client": client,
        "coordinator": coordinator,
        "diagnostics": {},
    }
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
