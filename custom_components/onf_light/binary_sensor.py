"""Binary sensor platform for ONF Light — BLE connection state."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import ONFLightDiagnosticCoordinator
from .data import ONFLightConfigEntry
from .entity import device_info_for_entry


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ONFLightConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up ONF Light binary sensors from a config entry."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities([ONFLightConnectedSensor(coordinator, entry)])


class ONFLightConnectedSensor(
    CoordinatorEntity[ONFLightDiagnosticCoordinator], BinarySensorEntity
):
    """Binary sensor that reflects whether the BLE connection is currently active.

    In addition to the coordinator's 30-second poll, the BLE client fires a
    callback on every connect and disconnect so the state updates immediately.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "connected"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: ONFLightDiagnosticCoordinator, entry: ONFLightConfigEntry) -> None:
        """Initialize the connected sensor."""
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_connected"
        self._attr_device_info = device_info_for_entry(entry)
        self._connection_callback = self._on_connection_changed

    async def async_added_to_hass(self) -> None:
        """Register BLE connection callback for real-time updates."""
        await super().async_added_to_hass()
        client = self._entry.runtime_data.client
        client.register_connection_callback(self._connection_callback)
        self.async_on_remove(
            lambda: client.unregister_connection_callback(self._connection_callback)
        )

    def _on_connection_changed(self) -> None:
        """Trigger an immediate coordinator refresh when BLE state changes."""
        self.hass.async_create_task(self.coordinator.async_request_refresh())

    @property
    def is_on(self) -> bool:
        """Return True when a BLE connection is currently open."""
        if not self.coordinator.data:
            return False
        return bool(self.coordinator.data.get("is_connected"))
