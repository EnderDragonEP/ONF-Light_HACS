"""Binary sensor platform for ONF Light — BLE connection state."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, EntityCategory
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
    """Set up ONF Light binary sensors from a config entry."""
    coordinator: ONFLightDiagnosticCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
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

    def __init__(self, coordinator: ONFLightDiagnosticCoordinator, entry: ConfigEntry) -> None:
        """Initialize the connected sensor."""
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_connected"
        self._connection_callback = self._on_connection_changed

    @property
    def device_info(self) -> DeviceInfo:
        """Attach to the shared ONF Light device."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.data[CONF_ADDRESS])},
            name=self._entry.title,
            manufacturer="ONF",
            model=self._entry.data.get(CONF_MODEL, self._entry.title),
        )

    async def async_added_to_hass(self) -> None:
        """Register BLE connection callback for real-time updates."""
        await super().async_added_to_hass()
        client = self.hass.data[DOMAIN][self._entry.entry_id]["client"]
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
