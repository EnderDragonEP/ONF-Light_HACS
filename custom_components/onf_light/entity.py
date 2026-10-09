"""Shared entity helpers for the ONF Light integration."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS
from homeassistant.helpers.device_registry import DeviceInfo

from .const import CONF_MODEL, DOMAIN


def device_info_for_entry(entry: ConfigEntry) -> DeviceInfo:
    """Return the device info shared by every entity of one light."""
    return DeviceInfo(
        identifiers={(DOMAIN, entry.data[CONF_ADDRESS])},
        name=entry.title,
        manufacturer="ONF",
        model=entry.data.get(CONF_MODEL, entry.title),
    )
