"""Config flow for ONF Light integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_ADDRESS

from .const import CONF_DEVICE_TYPE, CONF_MODEL, DEVICE_NAME_PREFIXES, DOMAIN, resolve_device_type

_LOGGER = logging.getLogger(__name__)


class ONFLightConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for ONF Light."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._discovery_info: BluetoothServiceInfoBleak | None = None
        self._discovered_devices: dict[str, BluetoothServiceInfoBleak] = {}

    @staticmethod
    def _device_name(discovery_info: BluetoothServiceInfoBleak) -> str:
        """Return user-facing device name."""
        return discovery_info.name or discovery_info.address

    @staticmethod
    def _is_supported_name(name: str) -> bool:
        """Return True if the Bluetooth name matches ONF device prefixes."""
        return any(name.startswith(prefix) for prefix in DEVICE_NAME_PREFIXES)

    def _entry_data(self, discovery_info: BluetoothServiceInfoBleak) -> dict[str, Any]:
        """Build config entry payload from discovery info."""
        name = self._device_name(discovery_info)
        return {
            CONF_ADDRESS: discovery_info.address,
            CONF_MODEL: name,
            CONF_DEVICE_TYPE: resolve_device_type(discovery_info.name),
        }

    async def _create_entry_for_discovery(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Create a config entry from a selected discovery."""
        await self.async_set_unique_id(
            discovery_info.address,
            raise_on_progress=False,
        )
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title=self._device_name(discovery_info),
            data=self._entry_data(discovery_info),
        )

    def _refresh_discovered_devices(self) -> None:
        """Populate in-memory list with currently discoverable supported devices."""
        current_addresses = self._async_current_ids()
        for discovery_info in async_discovered_service_info(self.hass, False):
            if discovery_info.address in current_addresses:
                continue
            name = self._device_name(discovery_info)
            if not self._is_supported_name(name):
                continue
            self._discovered_devices[discovery_info.address] = discovery_info

    def _build_device_options(self) -> dict[str, str]:
        """Build selector labels for the user step."""
        return {
            addr: f"{self._device_name(info)} ({addr})"
            for addr, info in self._discovered_devices.items()
        }

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Handle the Bluetooth discovery step."""
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()

        name = self._device_name(discovery_info)
        if not self._is_supported_name(name):
            return self.async_abort(reason="not_supported")

        self._discovery_info = discovery_info
        self.context["title_placeholders"] = {"name": name}
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm the Bluetooth discovery."""
        assert self._discovery_info is not None
        if user_input is not None:
            return await self._create_entry_for_discovery(self._discovery_info)

        return self.async_show_form(
            step_id="confirm",
            description_placeholders={
                "name": self._device_name(self._discovery_info)
            },
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the user step to pick discovered device."""
        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            discovery_info = self._discovered_devices.get(address)
            if discovery_info is None:
                return self.async_abort(reason="no_devices_found")
            return await self._create_entry_for_discovery(discovery_info)

        self._refresh_discovered_devices()

        if not self._discovered_devices:
            return self.async_abort(reason="no_devices_found")

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ADDRESS): vol.In(self._build_device_options())
                }
            ),
        )
