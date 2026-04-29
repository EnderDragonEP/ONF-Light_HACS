"""Constants for the ONF Light integration."""
from __future__ import annotations

from uuid import UUID

DOMAIN = "onf_light"
CONF_MODEL = "model"
CONF_DEVICE_TYPE = "device_type"

# Nordic UART Service UUIDs
SERVICE_UUID = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
CHAR_WRITE_UUID = UUID("6e400002-b5a3-f393-e0a9-e50e24dcca9e")
CHAR_NOTIFY_UUID = UUID("6e400003-b5a3-f393-e0a9-e50e24dcca9e")

# BLE device name prefixes
DEVICE_NAME_PREFIXES = ("ONF", "FLAT NANO+", "MIST O+")

DEVICE_TYPE_BY_NAME = {
	"ONF-1S": 0,
	"FLAT NANO+": 1,
	"ONF-1P": 2,
	"ONF-2S": 3,
	"ONF-2P": 4,
	"ONF-1S+": 5,
	"ONF-1P+": 6,
	"ONF-2S+": 7,
	"ONF-2P+": 8,
	"ONF-3S+": 9,
	"ONF-3P+": 10,
	"ONF-4S+": 11,
	"ONF-4P+": 12,
	"FLAT NANO++": 13,
	"FLAT NANO+ S": 14,
	"FLAT NANO+ BW": 15,
	"FLAT NANO+ YW": 16,
	"MIST O+ YW": 17,
	"MIST O+ BW": 18,
	"MIST O+ W": 19,
	"MIST O+ S": 20,
}

BRIGHTNESS_ONLY_TYPES = frozenset({1, 13, 14, 19, 20})
WARM_RANGE_TYPES = frozenset({17, 18})
BRIGHTNESS_STEP_PERCENT = 5

# Command timeout
BLE_TIMEOUT = 10.0
BLE_RESPONSE_TIMEOUT = 5.0
BLE_DISCONNECT_DELAY = 0.3
COMMAND_RETRIES = 3

# Connection management
IDLE_DISCONNECT_SECONDS = 30.0  # Disconnect after 30s of inactivity
COMMAND_DEBOUNCE_SECONDS = 0.15  # Debounce rapid slider adjustments
STATE_READBACK_DELAY = 0.06  # 60ms delay before reading state (matches app)
STATE_CONFIRM_RETRIES = 4  # Retry state confirmation before accepting stale data
STATE_CONFIRM_RETRY_DELAY = 0.12  # Delay between confirmation retries

# Polling
UPDATE_INTERVAL_SECONDS = 10  # Poll interval while idle
UNAVAILABLE_TRACK_FAILURES = 3  # Mark unavailable after N consecutive failures
UNAVAILABLE_POLL_DIVISOR = 6  # Only poll every Nth interval when unavailable (~60 s)

# Timer/schedule
MAX_TIMERS = 5
CONF_TIMERS = "timers"

# Options
CONF_POLL_INTERVAL = "poll_interval"
CONF_IDLE_DISCONNECT = "idle_disconnect"
CONF_TIME_SYNC_INTERVAL = "time_sync_interval"
TIME_SYNC_INTERVAL_MINUTES = 1440  # 24 hours


def kelvin_to_cct_internal(kelvin: int, device_type: int | None) -> int:
	"""Convert Kelvin to the device's 0–100 CCT internal value (5-step granularity)."""
	min_k, max_k = kelvin_range_for_type(device_type)
	kelvin = max(min_k, min(max_k, kelvin))
	internal = round((kelvin - min_k) / (max_k - min_k) * 100)
	return round(internal / BRIGHTNESS_STEP_PERCENT) * BRIGHTNESS_STEP_PERCENT


def resolve_device_type(name: str | None) -> int | None:
	"""Resolve the device type from the Bluetooth name."""
	if name is None:
		return None
	return DEVICE_TYPE_BY_NAME.get(name)


def is_brightness_only(device_type: int | None) -> bool:
	"""Return True when the device supports brightness only."""
	return device_type in BRIGHTNESS_ONLY_TYPES


def kelvin_range_for_type(device_type: int | None) -> tuple[int, int]:
	"""Return the supported Kelvin range for the device type."""
	if device_type in WARM_RANGE_TYPES:
		return (2700, 7000)
	return (3000, 6500)
