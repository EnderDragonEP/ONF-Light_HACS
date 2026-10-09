"""Pure helper functions for the ONF Light integration.

Nothing in this module imports Home Assistant, so it can be unit tested on its own.
"""
from __future__ import annotations

from typing import Any

from .const import (
    BRIGHTNESS_STEP_PERCENT,
    MAX_TIMERS,
    is_blue_white,
    kelvin_range_for_type,
)


# ── Brightness / colour temperature ──────────────────────────────────────────

def normalize_brightness_pct(brightness_pct: int) -> int:
    """Normalize brightness to the app's 5 percent steps."""
    brightness_pct = max(0, min(100, brightness_pct))
    return (brightness_pct // BRIGHTNESS_STEP_PERCENT) * BRIGHTNESS_STEP_PERCENT


def ha_to_brightness_pct(brightness_ha: int) -> int:
    """Convert HA brightness (0-255) to the device scale (0-100, 5-step)."""
    brightness_pct = round(brightness_ha / 255 * 100)
    if brightness_pct <= 0:
        return 0
    return max(BRIGHTNESS_STEP_PERCENT, normalize_brightness_pct(brightness_pct))


def brightness_pct_to_ha(brightness_pct: int) -> int:
    """Convert device brightness percent to HA brightness (0-255)."""
    brightness_pct = normalize_brightness_pct(brightness_pct)
    return round(brightness_pct / 100 * 255)


def normalize_cct_internal(cct_internal: int) -> int:
    """Normalize internal CCT to device protocol granularity (5-step)."""
    cct_internal = max(0, min(100, cct_internal))
    return round(cct_internal / BRIGHTNESS_STEP_PERCENT) * BRIGHTNESS_STEP_PERCENT


def cct_internal_to_kelvin(cct_internal: int, device_type: int | None) -> int:
    """Convert the device's 0-100 CCT value to the Kelvin label the app shows."""
    min_k, max_k = kelvin_range_for_type(device_type)
    fraction = normalize_cct_internal(cct_internal) / 100
    if is_blue_white(device_type):
        fraction = 1 - fraction  # Device value 0 is the blue (highest Kelvin) end.
    return round(min_k + fraction * (max_k - min_k))


def default_kelvin(device_type: int | None) -> int:
    """Return the midpoint of the device's Kelvin range (default for timers)."""
    min_k, max_k = kelvin_range_for_type(device_type)
    return round((min_k + max_k) / 2)


# ── Timers ───────────────────────────────────────────────────────────────────

def parse_time(time_str: str) -> tuple[int, int]:
    """Parse 'HH:MM' or 'HH:MM:SS' to (hour, minute), validating the range."""
    parts = time_str.split(":")
    if len(parts) < 2:
        raise ValueError(f"Invalid time '{time_str}', expected HH:MM")
    hour, minute = int(parts[0]), int(parts[1])
    if not (0 <= hour < 24 and 0 <= minute < 60):
        raise ValueError(f"Invalid time '{time_str}', out of range")
    return hour, minute


def normalize_timer_list(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return a MAX_TIMERS-long list of copied slots, padding with inactive slots."""
    result = [dict(timer) for timer in raw[:MAX_TIMERS]]
    while len(result) < MAX_TIMERS:
        result.append({"active": False})
    return result


def compact_timers(timers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Move active timers to the front, in order, as the official app stores them.

    The app reads device slots 1, 2, 3... and stops at the first inactive one,
    and always writes its timers to consecutive slots from slot 1. Sending HA's
    slots with gaps would leave the app unable to show the schedule.
    """
    active = [dict(timer) for timer in timers if timer.get("active")]
    return normalize_timer_list(active)


def relabel_timer_kelvin(
    timers: list[dict[str, Any]], device_type: int | None
) -> list[dict[str, Any]] | None:
    """Recompute stored Kelvin labels from each timer's device CCT value.

    Returns the updated list, or None when nothing changed. Keeps what the
    light actually does (cct_internal) and fixes the label, e.g. after the
    blue-white models moved to the app's 6500-20500 K scale.
    """
    changed = False
    result = []
    for timer in timers:
        timer = dict(timer)
        if "cct_internal" in timer:
            kelvin = cct_internal_to_kelvin(timer["cct_internal"], device_type)
            if timer.get("color_temp_kelvin") != kelvin:
                timer["color_temp_kelvin"] = kelvin
                changed = True
        result.append(timer)
    return result if changed else None
