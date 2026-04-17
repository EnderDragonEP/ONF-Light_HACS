"""Light platform for ONF Light integration."""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
    ColorMode,
    LightEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import CALLBACK_TYPE, HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval

from .ble_client import ONFLightBLEClient
from .const import (
    BRIGHTNESS_STEP_PERCENT,
    COMMAND_DEBOUNCE_SECONDS,
    CONF_DEVICE_TYPE,
    CONF_MODEL,
    DOMAIN,
    STATE_CONFIRM_RETRIES,
    STATE_CONFIRM_RETRY_DELAY,
    STATE_READBACK_DELAY,
    UNAVAILABLE_TRACK_FAILURES,
    UPDATE_INTERVAL_SECONDS,
    is_brightness_only,
    kelvin_range_for_type,
    resolve_device_type,
)

_LOGGER = logging.getLogger(__name__)


def _normalize_brightness_pct(brightness_pct: int) -> int:
    """Normalize brightness to the app's 5 percent steps."""
    brightness_pct = max(0, min(100, brightness_pct))
    return (brightness_pct // BRIGHTNESS_STEP_PERCENT) * BRIGHTNESS_STEP_PERCENT


def _ha_to_brightness_pct(brightness_ha: int) -> int:
    """Convert HA brightness to the device scale."""
    brightness_pct = round(brightness_ha / 255 * 100)
    if brightness_pct <= 0:
        return 0
    return max(BRIGHTNESS_STEP_PERCENT, _normalize_brightness_pct(brightness_pct))


def _brightness_pct_to_ha(brightness_pct: int) -> int:
    """Convert device brightness percent to HA brightness."""
    brightness_pct = _normalize_brightness_pct(brightness_pct)
    return round(brightness_pct / 100 * 255)


def _normalize_cct_internal(cct_internal: int) -> int:
    """Normalize internal CCT to device protocol granularity (5-step)."""
    cct_internal = max(0, min(100, cct_internal))
    return round(cct_internal / BRIGHTNESS_STEP_PERCENT) * BRIGHTNESS_STEP_PERCENT


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up ONF Light from a config entry."""
    address = entry.data[CONF_ADDRESS]
    client = ONFLightBLEClient(hass, address)
    entity = ONFLightEntity(entry, client)
    async_add_entities([entity])


class ONFLightEntity(LightEntity):
    """Representation of an ONF Light."""

    _attr_has_entity_name = True
    _attr_name = None

    def __init__(self, entry: ConfigEntry, client: ONFLightBLEClient) -> None:
        """Initialize the ONF Light entity."""
        self._entry = entry
        self._client = client
        self._address = entry.data[CONF_ADDRESS]
        self._model_name = entry.data.get(CONF_MODEL, entry.title)
        self._device_type = entry.data.get(CONF_DEVICE_TYPE)
        if self._device_type is None:
            self._device_type = resolve_device_type(self._model_name)
        self._brightness_only = is_brightness_only(self._device_type)
        self._min_kelvin, self._max_kelvin = kelvin_range_for_type(self._device_type)
        self._attr_unique_id = entry.entry_id
        self._brightness: int = 0
        self._cct_internal: int = 50
        self._is_on: bool = False
        self._available: bool = True
        self._last_brightness: int = 128
        self._consecutive_failures: int = 0
        self._debounce_task: asyncio.Task | None = None
        self._confirm_task: asyncio.Task | None = None
        self._unsub_interval: CALLBACK_TYPE | None = None
        self._pending_brightness_pct: int | None = None
        self._pending_cct_internal: int | None = None
        self._expected_brightness_pct: int | None = None
        self._expected_cct_internal: int | None = None
        if self._brightness_only:
            self._attr_color_mode = ColorMode.BRIGHTNESS
            self._attr_supported_color_modes = {ColorMode.BRIGHTNESS}
        else:
            self._attr_color_mode = ColorMode.COLOR_TEMP
            self._attr_supported_color_modes = {ColorMode.COLOR_TEMP}
            self._attr_min_color_temp_kelvin = self._min_kelvin
            self._attr_max_color_temp_kelvin = self._max_kelvin

    def _kelvin_to_internal(self, kelvin: int) -> int:
        """Convert Kelvin to the device CCT value."""
        kelvin = max(self._min_kelvin, min(self._max_kelvin, kelvin))
        internal = round(
            (kelvin - self._min_kelvin)
            / (self._max_kelvin - self._min_kelvin)
            * 100
        )
        return _normalize_cct_internal(internal)

    def _internal_to_kelvin(self, internal: int) -> int:
        """Convert the device CCT value to Kelvin."""
        internal = _normalize_cct_internal(internal)
        return round(
            self._min_kelvin
            + (internal / 100) * (self._max_kelvin - self._min_kelvin)
        )

    async def async_added_to_hass(self) -> None:
        """Run when entity is added to hass."""
        self._unsub_interval = async_track_time_interval(
            self.hass,
            self._async_poll_state,
            timedelta(seconds=UPDATE_INTERVAL_SECONDS),
        )

    async def async_will_remove_from_hass(self) -> None:
        """Clean up on removal."""
        if self._unsub_interval is not None:
            self._unsub_interval()
        self._cancel_task("_debounce_task")
        self._cancel_task("_confirm_task")
        await self._client.disconnect()

    @property
    def _has_pending_operation(self) -> bool:
        """Return True while a command is in-flight or being settled."""
        return self._debounce_task is not None or self._confirm_task is not None

    def _cancel_task(self, attr_name: str) -> None:
        """Cancel a task field and clear the reference."""
        task = getattr(self, attr_name)
        if task is not None:
            task.cancel()
            setattr(self, attr_name, None)

    def _clear_pending_command(self) -> None:
        """Clear the queued outgoing command values."""
        self._pending_brightness_pct = None
        self._pending_cct_internal = None

    def _clear_expected_state(self) -> None:
        """Clear optimistic expected state used by confirmation logic."""
        self._expected_brightness_pct = None
        self._expected_cct_internal = None

    def _mark_available(self) -> None:
        """Mark entity available and reset connectivity failures."""
        self._available = True
        self._consecutive_failures = 0

    def _register_failure(self, mark_unavailable: bool = True) -> None:
        """Track a failed device operation and mark unavailable if needed."""
        self._consecutive_failures += 1
        if mark_unavailable and self._consecutive_failures >= UNAVAILABLE_TRACK_FAILURES:
            self._available = False

    def _set_optimistic_state(self, brightness_pct: int, cct_internal: int | None) -> None:
        """Apply user-requested state immediately while device catches up."""
        self._is_on = brightness_pct > 0
        self._brightness = _brightness_pct_to_ha(brightness_pct)
        if self._is_on:
            self._last_brightness = self._brightness
        if cct_internal is not None and not self._brightness_only:
            self._cct_internal = cct_internal
        self._mark_available()
        self._expected_brightness_pct = brightness_pct
        self._expected_cct_internal = None if self._brightness_only else cct_internal

    def _queue_pending_command(self, brightness_pct: int, cct_internal: int | None) -> None:
        """Queue outgoing values for debounced transport."""
        self._pending_brightness_pct = brightness_pct
        self._pending_cct_internal = cct_internal

    async def _send_device_command(
        self, brightness_pct: int, cct_internal: int | None
    ) -> bool:
        """Send one command to the device based on entity capabilities."""
        if self._brightness_only:
            return await self._client.set_brightness(brightness_pct)
        if cct_internal is None:
            return False
        return await self._client.set_brightness_cct(brightness_pct, cct_internal)

    async def _handle_send_success(self) -> None:
        """Finalize state after successful command transmission."""
        self._consecutive_failures = 0
        await asyncio.sleep(STATE_READBACK_DELAY)
        self._confirm_task = asyncio.create_task(self._confirm_expected_state())

    def _handle_send_failure(self) -> None:
        """Finalize state after failed command transmission."""
        self._register_failure()
        self.async_write_ha_state()

    async def _async_poll_state(self, _now=None) -> None:
        """Poll the device state periodically."""
        if self._has_pending_operation:
            return
        await self._sync_state_from_device(mark_unavailable=True)

    async def _fetch_state_from_device(self) -> tuple[int, int | None] | None:
        """Fetch raw device state without mutating the entity."""
        if self._brightness_only:
            brightness_pct = await self._client.get_brightness_state()
            if brightness_pct is None:
                return None
            return (_normalize_brightness_pct(brightness_pct), None)

        state = await self._client.get_state()
        if state is None:
            return None
        brightness_pct, cct_internal = state
        return (_normalize_brightness_pct(brightness_pct), _normalize_cct_internal(cct_internal))

    def _apply_device_state(self, brightness_pct: int, cct_internal: int | None) -> None:
        """Apply a fetched device state to the entity."""
        self._is_on = brightness_pct > 0
        self._brightness = _brightness_pct_to_ha(brightness_pct)
        if self._is_on:
            self._last_brightness = self._brightness
        if cct_internal is not None:
            self._cct_internal = cct_internal
        self._mark_available()

    def _matches_expected_state(
        self, brightness_pct: int, cct_internal: int | None
    ) -> bool:
        """Return True when the fetched state matches the last requested state."""
        if self._expected_brightness_pct is None:
            return True
        if brightness_pct != self._expected_brightness_pct:
            return False
        if self._brightness_only:
            return True
        if self._expected_cct_internal is None:
            return True
        return cct_internal == self._expected_cct_internal

    async def _confirm_expected_state(self) -> None:
        """Wait for the device to report the newly requested state."""
        last_state: tuple[int, int | None] | None = None
        try:
            for _ in range(STATE_CONFIRM_RETRIES):
                state = await self._fetch_state_from_device()
                if state is None:
                    await asyncio.sleep(STATE_CONFIRM_RETRY_DELAY)
                    continue
                last_state = state
                brightness_pct, cct_internal = state
                if self._matches_expected_state(brightness_pct, cct_internal):
                    self._apply_device_state(brightness_pct, cct_internal)
                    self._clear_expected_state()
                    self.async_write_ha_state()
                    return
                await asyncio.sleep(STATE_CONFIRM_RETRY_DELAY)

            if last_state is not None:
                brightness_pct, cct_internal = last_state
                self._apply_device_state(brightness_pct, cct_internal)
                self.async_write_ha_state()
            else:
                self._register_failure()
                self.async_write_ha_state()
        finally:
            self._confirm_task = None
            self._clear_expected_state()

    async def _sync_state_from_device(self, mark_unavailable: bool = False) -> None:
        """Read back state from device and push to HA immediately."""
        state = await self._fetch_state_from_device()
        if state is not None:
            brightness_pct, cct_internal = state
            self._apply_device_state(brightness_pct, cct_internal)
            self.async_write_ha_state()
            return

        self._register_failure(mark_unavailable=mark_unavailable)
        self.async_write_ha_state()

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._address)},
            name=self._entry.title,
            manufacturer="ONF",
            model=self._model_name,
        )

    @property
    def is_on(self) -> bool:
        """Return true if light is on."""
        return self._is_on

    @property
    def brightness(self) -> int | None:
        """Return the brightness of the light."""
        return self._brightness

    @property
    def color_temp_kelvin(self) -> int | None:
        """Return the color temperature in Kelvin."""
        if self._brightness_only:
            return None
        return self._internal_to_kelvin(self._cct_internal)

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self._available

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the light on."""
        brightness_ha = kwargs.get(
            ATTR_BRIGHTNESS,
            self._last_brightness if not self._is_on else self._brightness,
        )
        brightness_pct = _ha_to_brightness_pct(brightness_ha)
        if brightness_pct == 0:
            brightness_pct = BRIGHTNESS_STEP_PERCENT

        cct_internal = self._cct_internal
        if not self._brightness_only and ATTR_COLOR_TEMP_KELVIN in kwargs:
            cct_internal = self._kelvin_to_internal(kwargs[ATTR_COLOR_TEMP_KELVIN])

        self._set_optimistic_state(brightness_pct, cct_internal)
        self.async_write_ha_state()

        self._queue_pending_command(brightness_pct, cct_internal)
        self._cancel_task("_debounce_task")
        self._cancel_task("_confirm_task")
        self._debounce_task = asyncio.create_task(self._debounced_send())

    async def _debounced_send(self) -> None:
        """Send the most recent command after a short debounce."""
        try:
            await asyncio.sleep(COMMAND_DEBOUNCE_SECONDS)
            brightness_pct = self._pending_brightness_pct
            cct_internal = self._pending_cct_internal
            if brightness_pct is None:
                return
            self._clear_pending_command()

            success = await self._send_device_command(brightness_pct, cct_internal)
            if not success:
                self._handle_send_failure()
                return

            await self._handle_send_success()
        finally:
            self._debounce_task = None

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the light off."""
        self._is_on = False
        self._brightness = 0
        self._expected_brightness_pct = 0
        self._expected_cct_internal = None
        self.async_write_ha_state()

        self._cancel_task("_debounce_task")
        self._cancel_task("_confirm_task")
        self._clear_pending_command()

        success = await self._client.set_brightness(0)
        if success:
            self._mark_available()
            await asyncio.sleep(STATE_READBACK_DELAY)
            self._confirm_task = asyncio.create_task(self._confirm_expected_state())
        else:
            self._register_failure()
            self.async_write_ha_state()

    async def async_update(self) -> None:
        """Fetch state from the device when first added."""
        await self._async_poll_state()


