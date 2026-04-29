"""BLE client for communicating with ONF Light devices.

Uses a hybrid connection pattern: keeps the BLE connection alive while actively
controlling the light, then auto-disconnects after an idle timeout. This gives
fast command throughput (like the app) without holding stale connections forever.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from datetime import datetime

from bleak import BleakClient
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
from homeassistant.components.bluetooth import async_ble_device_from_address
from homeassistant.core import HomeAssistant

from .const import (
    BLE_RESPONSE_TIMEOUT,
    BLE_TIMEOUT,
    CHAR_NOTIFY_UUID,
    CHAR_WRITE_UUID,
    COMMAND_RETRIES,
    IDLE_DISCONNECT_SECONDS,
)

_LOGGER = logging.getLogger(__name__)


class ONFLightBLEClient:
    """BLE client for ONF Light with idle-timeout managed connection."""

    def __init__(
        self,
        hass: HomeAssistant,
        address: str,
        idle_disconnect_seconds: float = IDLE_DISCONNECT_SECONDS,
    ) -> None:
        """Initialize the BLE client."""
        self._hass = hass
        self._address = address
        self._idle_disconnect_seconds: float = idle_disconnect_seconds
        self._lock = asyncio.Lock()
        self._client: BleakClient | None = None
        self._last_activity: float = 0.0
        self._idle_disconnect_task: asyncio.Task | None = None
        self._response_event = asyncio.Event()
        self._response_data: bytes = b""
        self._connection_callbacks: list[Callable[[], None]] = []

    @property
    def is_connected(self) -> bool:
        """Return True when a BLE connection is currently open."""
        return self._client is not None and self._client.is_connected

    def register_connection_callback(self, callback: Callable[[], None]) -> None:
        """Register a callback invoked whenever the BLE connection state changes."""
        self._connection_callbacks.append(callback)

    def unregister_connection_callback(self, callback: Callable[[], None]) -> None:
        """Remove a previously registered connection state callback."""
        try:
            self._connection_callbacks.remove(callback)
        except ValueError:
            pass

    def _fire_connection_callbacks(self) -> None:
        """Notify all registered listeners that the connection state has changed."""
        for cb in self._connection_callbacks:
            cb()

    def set_idle_disconnect_seconds(self, seconds: float) -> None:
        """Update the idle-disconnect timeout. -1 disables automatic disconnect."""
        self._idle_disconnect_seconds = seconds
        if self._idle_disconnect_task is not None:
            self._idle_disconnect_task.cancel()
            self._idle_disconnect_task = None
        if seconds >= 0 and self._client is not None and self._client.is_connected:
            self._schedule_idle_disconnect()

    def _get_ble_device(self) -> BLEDevice | None:
        """Get the BLEDevice from HA's Bluetooth manager."""
        return async_ble_device_from_address(
            self._hass, self._address, connectable=True
        )

    def _notification_handler(self, _sender: int, data: bytearray) -> None:
        """Handle BLE notification responses."""
        _LOGGER.debug("Received notification: %s", data)
        self._response_data = bytes(data)
        self._response_event.set()

    @staticmethod
    def _clamp_0_100(value: int) -> int:
        """Clamp protocol integer values to the valid range."""
        return max(0, min(100, value))

    @staticmethod
    def _decode_ascii_response(response: bytes) -> str:
        """Decode response payload and normalize trailing markers."""
        return response.decode("ascii").strip().rstrip("\x00")

    def _parse_state_response(self, response: bytes) -> tuple[int, int] | None:
        """Parse an lx? response payload into brightness and CCT."""
        try:
            text = self._decode_ascii_response(response)
            _LOGGER.debug("State response: '%s'", text)
            parts = text.split("%")
            if len(parts) < 2:
                return None
            return (int(parts[0]), int(parts[1]))
        except (ValueError, UnicodeDecodeError) as err:
            _LOGGER.warning(
                "Failed to parse state response '%s': %s", response, err
            )
            return None

    def _parse_brightness_response(self, response: bytes) -> int | None:
        """Parse an lv? response payload into brightness."""
        try:
            text = self._decode_ascii_response(response).replace("%", "")
            _LOGGER.debug("Brightness response: '%s'", text)
            return int(text)
        except (ValueError, UnicodeDecodeError) as err:
            _LOGGER.warning(
                "Failed to parse brightness response '%s': %s", response, err
            )
            return None

    async def _ensure_connected(self) -> BleakClient:
        """Get or create an active BLE connection."""
        if self._client is not None and self._client.is_connected:
            self._last_activity = time.monotonic()
            return self._client

        # Clean up dead client
        await self._do_disconnect()

        ble_device = self._get_ble_device()
        if ble_device is None:
            raise BleakError(
                f"Device {self._address} not found in Bluetooth manager"
            )

        _LOGGER.debug("Connecting to %s", self._address)
        client = BleakClient(ble_device, timeout=BLE_TIMEOUT)
        await client.connect()
        await client.start_notify(CHAR_NOTIFY_UUID, self._notification_handler)
        self._client = client
        self._last_activity = time.monotonic()
        _LOGGER.debug("Connected to %s", self._address)

        # Start idle-disconnect watchdog
        self._schedule_idle_disconnect()
        self._fire_connection_callbacks()

        return client

    def _schedule_idle_disconnect(self) -> None:
        """Schedule or reschedule the idle disconnect timer (no-op when disabled)."""
        if self._idle_disconnect_seconds < 0:
            return
        if self._idle_disconnect_task is not None:
            self._idle_disconnect_task.cancel()
        self._idle_disconnect_task = asyncio.create_task(
            self._idle_disconnect_loop()
        )

    async def _idle_disconnect_loop(self) -> None:
        """Periodically check if the connection has been idle too long."""
        try:
            while True:
                await asyncio.sleep(5.0)
                if self._client is None or not self._client.is_connected:
                    return
                if self._idle_disconnect_seconds < 0:
                    return
                elapsed = time.monotonic() - self._last_activity
                if elapsed >= self._idle_disconnect_seconds:
                    _LOGGER.debug(
                        "Idle timeout reached for %s, disconnecting", self._address
                    )
                    await self._do_disconnect()
                    return
        except asyncio.CancelledError:
            pass

    async def _do_disconnect(self) -> None:
        """Disconnect and clean up."""
        client = self._client
        had_connection = client is not None
        self._client = None
        if self._idle_disconnect_task is not None:
            self._idle_disconnect_task.cancel()
            self._idle_disconnect_task = None
        if client is not None and client.is_connected:
            try:
                await client.stop_notify(CHAR_NOTIFY_UUID)
            except (BleakError, OSError):
                pass
            try:
                await client.disconnect()
            except (BleakError, OSError):
                pass
        if had_connection:
            self._fire_connection_callbacks()

    async def disconnect(self) -> None:
        """Public disconnect."""
        async with self._lock:
            await self._do_disconnect()

    async def _send_command(
        self, data: bytes, wait_response: bool = False
    ) -> bytes | None:
        """Send a command over the managed connection."""
        async with self._lock:
            try:
                client = await self._ensure_connected()
            except (BleakError, TimeoutError, OSError) as err:
                _LOGGER.warning(
                    "Failed to connect to %s: %s", self._address, err
                )
                await self._do_disconnect()
                return None

            self._response_event.clear()
            self._response_data = b""

            _LOGGER.debug("Sending command to %s: %s", self._address, data)
            try:
                await client.write_gatt_char(CHAR_WRITE_UUID, data)
            except (BleakError, TimeoutError, OSError) as err:
                _LOGGER.warning(
                    "Failed to write to %s: %s", self._address, err
                )
                await self._do_disconnect()
                return None

            self._last_activity = time.monotonic()

            if wait_response:
                try:
                    await asyncio.wait_for(
                        self._response_event.wait(), timeout=BLE_RESPONSE_TIMEOUT
                    )
                    return self._response_data
                except TimeoutError:
                    _LOGGER.warning(
                        "Timeout waiting for response from %s", self._address
                    )
                    return None

            return b""

    async def _send_with_retry(
        self, data: bytes, wait_response: bool = False
    ) -> bytes | None:
        """Send command with retries, reconnecting on failure."""
        for attempt in range(1, COMMAND_RETRIES + 1):
            result = await self._send_command(data, wait_response)
            if result is not None:
                return result
            _LOGGER.debug(
                "Retry %d/%d for %s", attempt, COMMAND_RETRIES, self._address
            )
            # Force reconnect on retry
            async with self._lock:
                await self._do_disconnect()
        return None

    async def get_state(self) -> tuple[int, int] | None:
        """Get current brightness and CCT from the device.

        Returns:
            Tuple of (brightness 0-100, cct_internal 0-100) or None on failure.
        """
        response = await self._send_with_retry(b"lx?", wait_response=True)
        if response is None:
            return None
        return self._parse_state_response(response)

    async def get_brightness_state(self) -> int | None:
        """Get current brightness from a brightness-only device."""
        response = await self._send_with_retry(b"lv?", wait_response=True)
        if response is None:
            return None
        return self._parse_brightness_response(response)

    async def set_brightness_cct(self, brightness: int, cct_internal: int) -> bool:
        """Set brightness and CCT.

        Args:
            brightness: 0-100 percentage.
            cct_internal: 0-100 internal CCT value.

        Returns:
            True on success.
        """
        brightness = self._clamp_0_100(brightness)
        cct_internal = self._clamp_0_100(cct_internal)
        command = f"lx={brightness:03d},{cct_internal:03d}".encode("ascii")
        result = await self._send_with_retry(command, wait_response=True)
        return result is not None

    async def set_brightness(self, brightness: int) -> bool:
        """Set brightness only (0-100)."""
        brightness = self._clamp_0_100(brightness)
        command = f"lv={brightness:03d}".encode("ascii")
        result = await self._send_with_retry(command, wait_response=True)
        return result is not None

    async def get_firmware_version(self) -> str | None:
        """Get the firmware version."""
        response = await self._send_with_retry(b"rv?", wait_response=True)
        if response:
            try:
                return self._decode_ascii_response(response)
            except UnicodeDecodeError:
                pass
        return None

    async def sync_time(self) -> bool:
        """Sync the device's internal RTC to the current local time.

        Binary command A0: matches BLEManager.setTime() in the official app.
        Month is 0-indexed per Java Calendar.MONTH convention.
        0x5A is a fixed terminator byte (not a computed checksum).
        """
        now = datetime.now()
        year = now.year
        payload = bytes([
            0xA0,
            (year >> 8) & 0xFF,
            year & 0xFF,
            now.month - 1,  # 0-indexed (January = 0)
            now.day,
            now.hour,
            now.minute,
            now.second,
            0x5A,
        ])
        result = await self._send_with_retry(payload, wait_response=False)
        return result is not None

    # ── CCT timer protocol (for tunable-white devices) ──────────────────────

    async def set_timer_cct_time(
        self,
        slot: int,
        start_hour: int,
        start_minute: int,
        end_hour: int,
        end_minute: int,
    ) -> bool:
        """Send the start/end time for one CCT timer slot (B0+slot protocol).

        Matches BLEManager.saveTimerTimeB() with active=true.
        CRC = (cmd + 2 + startH + startM + endH + endM) % 256
        """
        cmd = 0xB0 + slot
        crc = (cmd + 2 + start_hour + start_minute + end_hour + end_minute) % 256
        payload = bytes([cmd, 0x01, 0x01, start_hour, start_minute, end_hour, end_minute, crc])
        result = await self._send_with_retry(payload, wait_response=False)
        return result is not None

    async def clear_timer_cct_time(self, slot: int) -> bool:
        """Clear one CCT timer slot (marks it inactive on the device).

        Matches BLEManager.saveTimerTimeB() with active=false.
        CRC = (cmd + 1) % 256
        """
        cmd = 0xB0 + slot
        crc = (cmd + 1) % 256
        payload = bytes([cmd, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, crc])
        result = await self._send_with_retry(payload, wait_response=False)
        return result is not None

    async def set_timers_cct_brightness(
        self,
        cct_values: list[int],
        br_values: list[int],
    ) -> bool:
        """Send brightness and CCT for all 5 timer slots at once (A3 protocol).

        Matches BLEManager.saveTimerBrightnessB().
        cct_values: 0-100 device units (pre-converted from Kelvin by caller).
        br_values:  0-100 percent.
        CRC = (0xA3 + 2 + sum_of_all_10_values) % 256
        """
        crc = (0xA3 + 2 + sum(cct_values) + sum(br_values)) % 256
        payload = bytes([0xA3, 0x01, 0x01] + cct_values + br_values + [crc])
        result = await self._send_with_retry(payload, wait_response=False)
        return result is not None

    # ── Simple (brightness-only) timer protocol ──────────────────────────────

    async def set_timers_simple_time(
        self,
        start_hour: int,
        start_minute: int,
        durations: list[int],
    ) -> bool:
        """Send all 5 timer time slots for a brightness-only device (A1 protocol).

        Matches BLEManager.saveTimerTime().
        durations: 5 chained durations in minutes (each as 2-byte big-endian).
          dur[0] = minutes from anchor start to end of timer 0.
          dur[N] = minutes from end of timer N-1 to end of timer N (gap).
        CRC = (0xA1 + 6 + startH + startM + sum_of_duration_bytes) % 256
        """
        dur_bytes: list[int] = []
        for d in durations:
            dur_bytes.extend([(d >> 8) & 0xFF, d & 0xFF])
        byte_sum = start_hour + start_minute + sum(dur_bytes)
        crc = (0xA1 + 6 + byte_sum) % 256
        payload = bytes([0xA1, 0x01, 0x05, start_hour, start_minute] + dur_bytes + [crc])
        result = await self._send_with_retry(payload, wait_response=False)
        return result is not None

    async def set_timers_simple_brightness(self, br_values: list[int]) -> bool:
        """Send brightness for all 5 timer slots for a brightness-only device (A2 protocol).

        Matches BLEManager.saveTimerBrightness().
        br_values: 0-100 percent, one per slot.
        CRC = (0xA2 + 2 + sum_of_brightness_values) % 256
        """
        crc = (0xA2 + 2 + sum(br_values)) % 256
        payload = bytes([0xA2, 0x01, 0x01] + br_values + [crc])
        result = await self._send_with_retry(payload, wait_response=False)
        return result is not None
