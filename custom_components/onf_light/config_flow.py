"""Config flow for ONF Light integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_DEVICE_TYPE,
    CONF_IDLE_DISCONNECT,
    CONF_MODEL,
    CONF_POLL_INTERVAL,
    CONF_TIME_SYNC_INTERVAL,
    CONF_TIMERS,
    DEVICE_NAME_PREFIXES,
    DOMAIN,
    IDLE_DISCONNECT_SECONDS,
    MAX_TIMERS,
    TIME_SYNC_INTERVAL_MINUTES,
    UPDATE_INTERVAL_SECONDS,
    is_brightness_only,
    kelvin_range_for_type,
    kelvin_to_cct_internal,
    resolve_device_type,
)

_LOGGER = logging.getLogger(__name__)


class ONFLightConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for ONF Light."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> "ONFLightOptionsFlowHandler":
        """Return the options flow handler (enables the gear icon in the UI)."""
        return ONFLightOptionsFlowHandler()

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


class ONFLightOptionsFlowHandler(OptionsFlow):
    """Options flow for configuring timers via the gear icon."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show timer configuration form."""
        device_type = self.config_entry.data.get(CONF_DEVICE_TYPE)
        brightness_only = is_brightness_only(device_type)
        min_k, max_k = kelvin_range_for_type(device_type)

        raw = self.config_entry.options.get(CONF_TIMERS, [])
        timers: list[dict] = list(raw[:MAX_TIMERS])
        while len(timers) < MAX_TIMERS:
            timers.append({"active": False})

        if user_input is not None:
            new_timers = self._parse_form(user_input, brightness_only, min_k, max_k, device_type)
            poll_interval = int(user_input.get(CONF_POLL_INTERVAL, UPDATE_INTERVAL_SECONDS))
            idle_disconnect = int(user_input.get(CONF_IDLE_DISCONNECT, IDLE_DISCONNECT_SECONDS))
            time_sync_interval = int(user_input.get(CONF_TIME_SYNC_INTERVAL, TIME_SYNC_INTERVAL_MINUTES))
            new_options = {
                **self.config_entry.options,
                CONF_TIMERS: new_timers,
                CONF_POLL_INTERVAL: poll_interval,
                CONF_IDLE_DISCONNECT: idle_disconnect,
                CONF_TIME_SYNC_INTERVAL: time_sync_interval,
            }

            entry_data = self.hass.data.get(DOMAIN, {}).get(self.config_entry.entry_id, {})
            entity = entry_data.get("entity")
            if entity is not None:
                await entity.async_send_timers_to_device(new_timers)
                entity.async_write_ha_state()

            return self.async_create_entry(title="", data=new_options)

        return self.async_show_form(
            step_id="init",
            data_schema=self._build_schema(timers, brightness_only, min_k, max_k),
        )

    def _build_schema(
        self,
        timers: list[dict],
        brightness_only: bool,
        min_k: int,
        max_k: int,
    ) -> vol.Schema:
        """Build the timer configuration form schema."""
        current_interval = self.config_entry.options.get(
            CONF_POLL_INTERVAL, UPDATE_INTERVAL_SECONDS
        )
        current_idle = self.config_entry.options.get(
            CONF_IDLE_DISCONNECT, IDLE_DISCONNECT_SECONDS
        )
        current_sync = self.config_entry.options.get(
            CONF_TIME_SYNC_INTERVAL, TIME_SYNC_INTERVAL_MINUTES
        )
        schema: dict = {
            vol.Optional(CONF_POLL_INTERVAL, default=current_interval): (
                selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0,
                        max=3600,
                        unit_of_measurement="s",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                )
            ),
            vol.Optional(CONF_IDLE_DISCONNECT, default=current_idle): (
                selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=-1,
                        max=3600,
                        unit_of_measurement="s",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                )
            ),
            vol.Optional(CONF_TIME_SYNC_INTERVAL, default=current_sync): (
                selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0,
                        max=10080,
                        unit_of_measurement="min",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                )
            ),
        }
        mid_k = round((min_k + max_k) / 2)

        for i, timer in enumerate(timers, start=1):
            active = timer.get("active", False)
            start = timer.get("start", "07:00:00")
            end = timer.get("end", "22:00:00")
            if len(start) == 5:
                start += ":00"
            if len(end) == 5:
                end += ":00"
            brightness = timer.get("brightness", 80)

            schema[vol.Optional(f"slot_{i}_enabled", default=active)] = (
                selector.BooleanSelector()
            )
            schema[vol.Optional(f"slot_{i}_start", default=start)] = (
                selector.TimeSelector()
            )
            schema[vol.Optional(f"slot_{i}_end", default=end)] = (
                selector.TimeSelector()
            )
            schema[vol.Optional(f"slot_{i}_brightness", default=brightness)] = (
                selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0,
                        max=100,
                        unit_of_measurement="%",
                        mode=selector.NumberSelectorMode.SLIDER,
                    )
                )
            )
            if not brightness_only:
                default_k = timer.get("color_temp_kelvin", mid_k)
                schema[vol.Optional(f"slot_{i}_color_temp", default=default_k)] = (
                    selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=min_k,
                            max=max_k,
                            unit_of_measurement="K",
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    )
                )

        return vol.Schema(schema)

    def _parse_form(
        self,
        user_input: dict[str, Any],
        brightness_only: bool,
        min_k: int,
        max_k: int,
        device_type: int | None,
    ) -> list[dict]:
        """Parse form values into the timer list structure."""
        timers: list[dict] = []
        for i in range(1, MAX_TIMERS + 1):
            enabled = user_input.get(f"slot_{i}_enabled", False)
            if not enabled:
                timers.append({"active": False})
                continue

            start: str = user_input.get(f"slot_{i}_start", "07:00:00")
            end: str = user_input.get(f"slot_{i}_end", "22:00:00")
            brightness = int(user_input.get(f"slot_{i}_brightness", 80))
            start_hm = start[:5]
            end_hm = end[:5]
            sh, sm = int(start[:2]), int(start[3:5])
            eh, em = int(end[:2]), int(end[3:5])

            timer: dict[str, Any] = {
                "active": True,
                "start": start_hm,
                "end": end_hm,
                "start_hour": sh,
                "start_minute": sm,
                "end_hour": eh,
                "end_minute": em,
                "brightness": max(0, min(100, brightness)),
            }
            if not brightness_only:
                mid_k = round((min_k + max_k) / 2)
                k = int(user_input.get(f"slot_{i}_color_temp", mid_k))
                k = max(min_k, min(max_k, k))
                timer["color_temp_kelvin"] = k
                timer["cct_internal"] = kelvin_to_cct_internal(k, device_type)
            timers.append(timer)
        return timers
