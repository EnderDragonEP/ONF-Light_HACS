"""Sensor platform for ONF Light — diagnostic entities."""
from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, EntityCategory, SIGNAL_STRENGTH_DECIBELS_MILLIWATT
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_MODEL, DOMAIN
from .coordinator import ONFLightDiagnosticCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up ONF Light diagnostic sensors from a config entry."""
    coordinator: ONFLightDiagnosticCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities([
        ONFLightFirmwareSensor(coordinator, entry),
        ONFLightSignalStrengthSensor(coordinator, entry),
        ONFLightKelvinRangeSensor(coordinator, entry),
        ONFLightActiveTimersSensor(coordinator, entry),
    ])


class _ONFLightDiagnosticSensor(CoordinatorEntity[ONFLightDiagnosticCoordinator], SensorEntity):
    """Shared base for all ONF Light diagnostic sensors."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: ONFLightDiagnosticCoordinator, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._entry = entry

    @property
    def device_info(self) -> DeviceInfo:
        """Attach to the shared ONF Light device."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.data[CONF_ADDRESS])},
            name=self._entry.title,
            manufacturer="ONF",
            model=self._entry.data.get(CONF_MODEL, self._entry.title),
        )


class ONFLightFirmwareSensor(_ONFLightDiagnosticSensor):
    """Reports the device firmware version string."""

    _attr_translation_key = "firmware_version"
    _attr_icon = "mdi:chip"
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: ONFLightDiagnosticCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_firmware_version"

    @property
    def native_value(self) -> str | None:
        """Return firmware version, or None until fetched."""
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get("firmware_version")


class ONFLightSignalStrengthSensor(_ONFLightDiagnosticSensor):
    """Reports the last advertised RSSI from the Bluetooth stack."""

    _attr_translation_key = "signal_strength"
    _attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH
    _attr_native_unit_of_measurement = SIGNAL_STRENGTH_DECIBELS_MILLIWATT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: ONFLightDiagnosticCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_rssi"

    @property
    def native_value(self) -> int | None:
        """Return RSSI in dBm from the most recent BLE advertisement."""
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get("rssi")


class ONFLightKelvinRangeSensor(_ONFLightDiagnosticSensor):
    """Reports the device's color temperature capability."""

    _attr_translation_key = "kelvin_range"
    _attr_icon = "mdi:thermometer-lines"
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: ONFLightDiagnosticCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_kelvin_range"

    @property
    def native_value(self) -> str:
        """Return Kelvin range string, or 'Brightness Only' for dimmer-only devices."""
        if not self.coordinator.data:
            return "Unknown"
        if self.coordinator.data.get("brightness_only"):
            return "Brightness Only"
        min_k, max_k = self.coordinator.data.get("kelvin_range", (3000, 6500))
        return f"{min_k}K – {max_k}K"


class ONFLightActiveTimersSensor(_ONFLightDiagnosticSensor):
    """Reports the count of active on-device timer slots, with schedule details as attributes."""

    _attr_translation_key = "active_timers"
    _attr_icon = "mdi:timer-outline"
    _attr_native_unit_of_measurement = "slots"

    def __init__(self, coordinator: ONFLightDiagnosticCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_active_timers"

    @property
    def native_value(self) -> int:
        """Return the number of currently active timer slots (0–5)."""
        if not self.coordinator.data:
            return 0
        return self.coordinator.data.get("active_timer_count", 0)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return per-slot schedule details for active timers."""
        if not self.coordinator.data:
            return {}
        attrs: dict[str, Any] = {}
        for i, timer in enumerate(self.coordinator.data.get("timers", []), start=1):
            if timer.get("active"):
                slot: dict[str, Any] = {
                    "start": timer.get("start", ""),
                    "end": timer.get("end", ""),
                    "brightness": timer.get("brightness", 0),
                }
                if "color_temp_kelvin" in timer:
                    slot["color_temp_kelvin"] = timer["color_temp_kelvin"]
                attrs[f"slot_{i}"] = slot
        return attrs
