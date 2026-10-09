"""Light platform for ONF Light integration."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine
from datetime import time as dt_time, timedelta
from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
    ColorMode,
    LightEntity,
)
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import CALLBACK_TYPE, HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.entity_platform import (
    AddEntitiesCallback,
    async_get_current_platform,
)
from homeassistant.helpers.event import async_track_time_interval

from .const import (
    BRIGHTNESS_STEP_PERCENT,
    COMMAND_DEBOUNCE_SECONDS,
    CONF_DEVICE_TYPE,
    CONF_IDLE_DISCONNECT,
    CONF_MODEL,
    CONF_POLL_INTERVAL,
    CONF_TIME_SYNC_INTERVAL,
    CONF_TIMERS,
    DOMAIN,
    IDLE_DISCONNECT_SECONDS,
    MAX_TIMERS,
    STATE_CONFIRM_RETRIES,
    STATE_CONFIRM_RETRY_DELAY,
    STATE_READBACK_DELAY,
    TIME_SYNC_INTERVAL_MINUTES,
    UNAVAILABLE_POLL_DIVISOR,
    UNAVAILABLE_TRACK_FAILURES,
    UPDATE_INTERVAL_SECONDS,
    is_brightness_only,
    kelvin_range_for_type,
    kelvin_to_cct_internal,
    resolve_device_type,
)
from .entity import device_info_for_entry
from .helpers import (
    brightness_pct_to_ha,
    cct_internal_to_kelvin,
    compact_timers,
    default_kelvin,
    ha_to_brightness_pct,
    normalize_brightness_pct,
    normalize_cct_internal,
    normalize_timer_list,
    parse_time,
)

if TYPE_CHECKING:
    from .ble_client import ONFLightBLEClient
    from .data import ONFLightConfigEntry

_LOGGER = logging.getLogger(__name__)

# ── Service schemas ──────────────────────────────────────────────────────────

SET_TIMER_SCHEMA = {
    vol.Required("slot"): vol.All(vol.Coerce(int), vol.Range(min=1, max=MAX_TIMERS)),
    vol.Required("start_time"): cv.time,
    vol.Required("end_time"): cv.time,
    vol.Required("brightness"): vol.All(vol.Coerce(int), vol.Range(min=0, max=100)),
    # Widest range of any model (blue-white MIST O+ BW goes to 21000 K); the
    # value is clamped to the target light's own range.
    vol.Optional("color_temp_kelvin"): vol.All(
        vol.Coerce(int), vol.Range(min=2700, max=21000)
    ),
}

CLEAR_TIMER_SCHEMA = {
    vol.Optional("slot"): vol.All(vol.Coerce(int), vol.Range(min=1, max=MAX_TIMERS)),
}


# ── Platform setup ────────────────────────────────────────────────────────────

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ONFLightConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up ONF Light from a config entry."""
    entity = ONFLightEntity(entry, entry.runtime_data.client)
    entry.runtime_data.entity = entity
    async_add_entities([entity])

    platform = async_get_current_platform()
    platform.async_register_entity_service("set_timer", SET_TIMER_SCHEMA, "async_set_timer")
    platform.async_register_entity_service("clear_timer", CLEAR_TIMER_SCHEMA, "async_clear_timer")


# ── Entity ───────────────────────────────────────────────────────────────────

class ONFLightEntity(LightEntity):
    """Representation of an ONF Light."""

    _attr_has_entity_name = True
    _attr_name = None
    # Polling is driven by our own configurable timer, not HA's 30 s scan.
    _attr_should_poll = False

    def __init__(self, entry: ONFLightConfigEntry, client: ONFLightBLEClient) -> None:
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
        self._attr_device_info = device_info_for_entry(entry)
        self._brightness: int = 0
        self._cct_internal: int = 50
        self._is_on: bool = False
        self._available: bool = True
        self._last_brightness: int = 128
        self._consecutive_failures: int = 0
        self._poll_skip_counter: int = 0
        self._debounce_task: asyncio.Task | None = None
        self._confirm_task: asyncio.Task | None = None
        self._unsub_interval: CALLBACK_TYPE | None = None
        self._unsub_sync_interval: CALLBACK_TYPE | None = None
        self._pending_brightness_pct: int | None = None
        self._pending_cct_internal: int | None = None
        self._expected_brightness_pct: int | None = None
        self._expected_cct_internal: int | None = None
        self._firmware_version: str | None = None
        self._firmware_fetched: bool = False
        self._time_synced: bool = False
        self._timers_pushed: bool = False
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
        return kelvin_to_cct_internal(kelvin, self._device_type)

    def _internal_to_kelvin(self, internal: int) -> int:
        """Convert the device CCT value to Kelvin."""
        return cct_internal_to_kelvin(internal, self._device_type)

    def _start_background(self, coro: Coroutine[Any, Any, Any], name: str) -> None:
        """Run a one-shot job that is tracked and cancelled when the entry unloads."""
        self._entry.async_create_background_task(
            self.hass, coro, f"{DOMAIN} {name} {self._address}"
        )

    async def async_added_to_hass(self) -> None:
        """Run when entity is added to hass."""
        self._restart_poll_timer()
        self._restart_sync_timer()
        self.async_on_remove(
            self._entry.add_update_listener(self._async_options_updated)
        )
        # Read the initial state now instead of waiting for the first poll tick.
        self._start_background(self._async_poll_state(), "initial poll")

    def _restart_poll_timer(self) -> None:
        """Start or restart the polling timer from the current configured interval."""
        if self._unsub_interval is not None:
            self._unsub_interval()
            self._unsub_interval = None
        interval = self._entry.options.get(CONF_POLL_INTERVAL, UPDATE_INTERVAL_SECONDS)
        if interval > 0:
            self._unsub_interval = async_track_time_interval(
                self.hass,
                self._async_poll_state,
                timedelta(seconds=interval),
            )

    def _restart_sync_timer(self) -> None:
        """Start or restart the periodic clock-sync timer from the current configured interval."""
        if self._unsub_sync_interval is not None:
            self._unsub_sync_interval()
            self._unsub_sync_interval = None
        interval_minutes = self._entry.options.get(
            CONF_TIME_SYNC_INTERVAL, TIME_SYNC_INTERVAL_MINUTES
        )
        if interval_minutes > 0:
            self._unsub_sync_interval = async_track_time_interval(
                self.hass,
                self._async_periodic_time_sync,
                timedelta(minutes=interval_minutes),
            )

    async def _async_periodic_time_sync(self, _now=None) -> None:
        """Sync the device RTC on the configured schedule."""
        success = await self._client.sync_time()
        _LOGGER.debug(
            "Periodic time sync for %s: %s", self._address, "ok" if success else "failed"
        )

    async def _async_options_updated(
        self, hass: HomeAssistant, entry: ONFLightConfigEntry
    ) -> None:
        """Apply updated options: poll interval, idle-disconnect timeout, sync interval."""
        self._restart_poll_timer()
        self._restart_sync_timer()
        idle_seconds = float(entry.options.get(CONF_IDLE_DISCONNECT, IDLE_DISCONNECT_SECONDS))
        self._client.set_idle_disconnect_seconds(idle_seconds)
        self.async_write_ha_state()  # Timer attributes come from options.
        await entry.runtime_data.coordinator.async_request_refresh()

    async def async_will_remove_from_hass(self) -> None:
        """Clean up on removal."""
        if self._unsub_interval is not None:
            self._unsub_interval()
        if self._unsub_sync_interval is not None:
            self._unsub_sync_interval()
        self._cancel_task("_debounce_task")
        self._cancel_task("_confirm_task")
        if self._entry.runtime_data.entity is self:
            self._entry.runtime_data.entity = None
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
        self._poll_skip_counter = 0

    def _register_failure(self, mark_unavailable: bool = True) -> None:
        """Track a failed device operation and mark unavailable if needed."""
        self._consecutive_failures += 1
        if mark_unavailable and self._consecutive_failures >= UNAVAILABLE_TRACK_FAILURES:
            self._available = False

    def _set_optimistic_state(self, brightness_pct: int, cct_internal: int | None) -> None:
        """Apply user-requested state immediately while device catches up."""
        self._is_on = brightness_pct > 0
        self._brightness = brightness_pct_to_ha(brightness_pct)
        if self._is_on:
            self._last_brightness = self._brightness
        if cct_internal is not None and not self._brightness_only:
            self._cct_internal = cct_internal
        self._mark_available()
        self._expected_brightness_pct = brightness_pct
        self._expected_cct_internal = None if self._brightness_only else cct_internal

    def _schedule_send(self, brightness_pct: int, cct_internal: int | None) -> None:
        """Queue outgoing values and (re)start the debounced send task."""
        self._pending_brightness_pct = brightness_pct
        self._pending_cct_internal = cct_internal
        self._cancel_task("_debounce_task")
        self._cancel_task("_confirm_task")
        self._debounce_task = asyncio.create_task(self._debounced_send())

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
        """Poll the device state periodically, backing off when unavailable."""
        if self._has_pending_operation:
            return
        if not self._available:
            self._poll_skip_counter += 1
            if self._poll_skip_counter % UNAVAILABLE_POLL_DIVISOR != 0:
                return
        await self._sync_state_from_device(mark_unavailable=True)

    async def _fetch_state_from_device(self) -> tuple[int, int | None] | None:
        """Fetch raw device state without mutating the entity."""
        if self._brightness_only:
            brightness_pct = await self._client.get_brightness_state()
            if brightness_pct is None:
                return None
            return (normalize_brightness_pct(brightness_pct), None)

        state = await self._client.get_state()
        if state is None:
            return None
        brightness_pct, cct_internal = state
        return (normalize_brightness_pct(brightness_pct), normalize_cct_internal(cct_internal))

    def _apply_device_state(self, brightness_pct: int, cct_internal: int | None) -> None:
        """Apply a fetched device state to the entity and trigger one-shot tasks."""
        self._is_on = brightness_pct > 0
        self._brightness = brightness_pct_to_ha(brightness_pct)
        if self._is_on:
            self._last_brightness = self._brightness
        if cct_internal is not None:
            self._cct_internal = cct_internal
        self._mark_available()

        if not self._firmware_fetched:
            self._firmware_fetched = True
            self._start_background(self._fetch_firmware_version(), "firmware fetch")

        if not self._time_synced:
            self._time_synced = True
            self._start_background(self._sync_device_time(), "time sync")

        if not self._timers_pushed:
            self._timers_pushed = True
            self._start_background(self._push_stored_timers(), "timer push")

    async def _fetch_firmware_version(self) -> None:
        """Fetch firmware version once and publish to diagnostics store and coordinator."""
        version = await self._client.get_firmware_version()
        if not version:
            self._firmware_fetched = False  # Try again on the next successful read.
            return
        self._firmware_version = version
        _LOGGER.debug("Firmware version for %s: %s", self._address, version)
        self._entry.runtime_data.diagnostics["firmware_version"] = version
        await self._entry.runtime_data.coordinator.async_request_refresh()
        self.async_write_ha_state()

    async def _sync_device_time(self) -> None:
        """Sync the device RTC to current local time."""
        success = await self._client.sync_time()
        if not success:
            self._time_synced = False  # Try again on the next successful read.
        _LOGGER.debug("Time sync for %s: %s", self._address, "ok" if success else "failed")

    async def _push_stored_timers(self) -> None:
        """Push the timer schedule stored in options to the device.

        Runs after the first successful read, and again after any failed push.
        Skipped only when timers were never configured in HA, so schedules set
        up in the official app are left alone. An all-inactive list is still
        pushed, so clearing timers while the light was offline takes effect.
        """
        if CONF_TIMERS not in self._entry.options:
            return
        timers = normalize_timer_list(self._entry.options[CONF_TIMERS])
        _LOGGER.debug("Pushing stored timers to %s", self._address)
        await self.async_send_timers_to_device(timers)

    async def async_send_timers_to_device(self, timers: list[dict[str, Any]]) -> bool:
        """Send the full timer configuration to the device.

        Returns True on success. On failure the push is retried automatically
        after the next successful state read.
        """
        sent = await self._write_timers(timers)
        self._timers_pushed = sent
        if not sent:
            _LOGGER.warning(
                "Could not send timer schedule to %s; will retry when it is reachable",
                self._address,
            )
        return sent

    async def _write_timers(self, timers: list[dict[str, Any]]) -> bool:
        """Write the schedule the way ONF Link 2.5.1 does, stopping at the first failure.

        Active timers go to consecutive device slots from slot 1, then B1-B5
        carry each slot's times and one A2 (brightness-only) or A3 (CCT)
        command carries the levels for all five slots.
        """
        client = self._client
        timers = compact_timers(timers)
        for i, timer in enumerate(timers, start=1):
            if timer.get("active"):
                sh, sm = parse_time(timer.get("start", "00:00"))
                eh, em = parse_time(timer.get("end", "00:00"))
                sent = await client.set_timer_slot_time(i, sh, sm, eh, em)
            else:
                sent = await client.clear_timer_slot(i)
            if not sent:
                return False

        br_values = [t.get("brightness", 0) for t in timers]
        if self._brightness_only:
            return await client.set_timers_brightness(br_values)
        cct_values = [t.get("cct_internal", 0) for t in timers]
        return await client.set_timers_cct_brightness(cct_values, br_values)

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
            # A cancelled task finishes after its replacement has started; only
            # clear shared state if we are still the current confirm task.
            if self._confirm_task is asyncio.current_task():
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

    # ── HA properties ────────────────────────────────────────────────────────

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

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return diagnostic and timer attributes."""
        attrs: dict[str, Any] = {}
        if self._firmware_version:
            attrs["firmware_version"] = self._firmware_version
        timers = self._entry.options.get(CONF_TIMERS, [])
        if timers:
            attrs["timers"] = timers
        return attrs

    # ── Service calls ────────────────────────────────────────────────────────

    async def async_set_timer(
        self,
        slot: int,
        start_time: dt_time,
        end_time: dt_time,
        brightness: int,
        color_temp_kelvin: int | None = None,
    ) -> None:
        """Set a timer slot and push the full schedule to the device."""
        sh, sm = start_time.hour, start_time.minute
        eh, em = end_time.hour, end_time.minute

        new_timer: dict[str, Any] = {
            "active": True,
            "start": f"{sh:02d}:{sm:02d}",
            "end": f"{eh:02d}:{em:02d}",
            "start_hour": sh,
            "start_minute": sm,
            "end_hour": eh,
            "end_minute": em,
            "brightness": max(0, min(100, brightness)),
        }
        if not self._brightness_only:
            # Same default as the options form: the middle of the Kelvin range.
            if color_temp_kelvin is None:
                color_temp_kelvin = default_kelvin(self._device_type)
            k = max(self._min_kelvin, min(self._max_kelvin, color_temp_kelvin))
            new_timer["color_temp_kelvin"] = k
            new_timer["cct_internal"] = self._kelvin_to_internal(k)

        timers = normalize_timer_list(self._entry.options.get(CONF_TIMERS, []))
        timers[slot - 1] = new_timer
        await self._async_save_and_send_timers(timers)

    async def async_clear_timer(self, slot: int | None = None) -> None:
        """Clear one or all timer slots and push the updated schedule."""
        timers = normalize_timer_list(self._entry.options.get(CONF_TIMERS, []))
        if slot is None:
            timers = [{"active": False} for _ in range(MAX_TIMERS)]
        else:
            timers[slot - 1] = {"active": False}
        await self._async_save_and_send_timers(timers)

    async def _async_save_and_send_timers(self, timers: list[dict[str, Any]]) -> None:
        """Persist and push a schedule, raising if the push fails."""
        new_options = {**self._entry.options, CONF_TIMERS: timers}
        self.hass.config_entries.async_update_entry(self._entry, options=new_options)
        sent = await self.async_send_timers_to_device(timers)
        self.async_write_ha_state()
        if not sent:
            raise HomeAssistantError(
                f"The schedule was saved, but it could not be sent to "
                f"{self._entry.title}. It will be sent automatically when the "
                "light is reachable again."
            )

    # ── Light commands ───────────────────────────────────────────────────────

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the light on."""
        brightness_ha = kwargs.get(
            ATTR_BRIGHTNESS,
            self._last_brightness if not self._is_on else self._brightness,
        )
        brightness_pct = ha_to_brightness_pct(brightness_ha)
        if brightness_pct == 0:
            brightness_pct = BRIGHTNESS_STEP_PERCENT

        cct_internal = self._cct_internal
        if not self._brightness_only and ATTR_COLOR_TEMP_KELVIN in kwargs:
            cct_internal = self._kelvin_to_internal(kwargs[ATTR_COLOR_TEMP_KELVIN])

        self._set_optimistic_state(brightness_pct, cct_internal)
        self.async_write_ha_state()
        self._schedule_send(brightness_pct, cct_internal)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the light off.

        CCT devices receive lx=000,CCC (matching setDimmerB in the official app).
        Brightness-only devices receive lv=000. The command goes through the
        same debounced background path as turn_on, so the service call never
        blocks on a slow or unreachable light.
        """
        self._set_optimistic_state(0, None)
        self.async_write_ha_state()
        self._schedule_send(0, None if self._brightness_only else self._cct_internal)

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
            # A cancelled task finishes after its replacement has started; don't
            # clear the reference to the new task.
            if self._debounce_task is asyncio.current_task():
                self._debounce_task = None

    async def async_update(self) -> None:
        """Refresh state on demand (homeassistant.update_entity)."""
        await self._async_poll_state()
