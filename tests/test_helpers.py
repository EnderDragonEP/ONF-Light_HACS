"""Unit tests for the pure helper functions (run with: pytest).

The colour temperature expectations are the formulas from the official
ONF Link 2.5.1 Android app (DimmerBigFragment / BLEManager.setDimmerB).
"""
import pytest

from onf_light.const import DEVICE_TYPE_BY_NAME, is_brightness_only, kelvin_to_cct_internal
from onf_light.helpers import (
    brightness_pct_to_ha,
    cct_internal_to_kelvin,
    compact_timers,
    default_kelvin,
    ha_to_brightness_pct,
    normalize_timer_list,
    parse_time,
    relabel_timer_kelvin,
)

STANDARD = 3  # ONF-2S: 3000-6500 K
WARM = 17  # MIST O+ YW: 2700-7000 K
BLUE_WHITE = 0  # ONF-1S: 6500-20500 K, reversed
MIST_BW = 18  # MIST O+ BW: 7000-21000 K, reversed

CCT_TYPES = sorted(t for t in DEVICE_TYPE_BY_NAME.values() if not is_brightness_only(t))


def app_slider_kelvin(device_type: int, progress: int) -> int:
    """Kelvin label the app shows for CCT slider position 0-20."""
    if device_type in (0, 5, 9, 2, 6, 10, 15, 18):  # blue-white drawable
        base = 7000 if device_type == 18 else 6500
        return (20 - progress) * 700 + base
    if device_type == 17:
        return progress * 215 + 2700
    return progress * 175 + 3000


def app_device_value(device_type: int, progress: int) -> int:
    """CCT value the app sends in lx=BBB,CCC for slider position 0-20."""
    kelvin = progress * 215 + 2700 if device_type in (17, 18) else progress * 175 + 3000
    return (kelvin - 2700) // 43 if device_type in (17, 18) else (kelvin - 3000) // 35


# ── Brightness ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("pct", range(0, 101, 5))
def test_brightness_round_trip(pct):
    assert ha_to_brightness_pct(brightness_pct_to_ha(pct)) == pct


def test_brightness_extremes():
    assert ha_to_brightness_pct(0) == 0
    assert ha_to_brightness_pct(255) == 100
    assert brightness_pct_to_ha(100) == 255


def test_tiny_brightness_rounds_up_to_lowest_step():
    # 3/255 is about 1 %, which must not become "off".
    assert ha_to_brightness_pct(3) == 5


# ── Colour temperature, checked against the app for every CCT model ──────────

@pytest.mark.parametrize("device_type", CCT_TYPES)
@pytest.mark.parametrize("progress", range(21))
def test_kelvin_matches_app(device_type, progress):
    value = app_device_value(device_type, progress)
    assert value == progress * 5
    assert cct_internal_to_kelvin(value, device_type) == app_slider_kelvin(device_type, progress)
    assert kelvin_to_cct_internal(app_slider_kelvin(device_type, progress), device_type) == value


def test_blue_white_scale_is_reversed():
    assert cct_internal_to_kelvin(0, BLUE_WHITE) == 20500  # blue end
    assert cct_internal_to_kelvin(100, BLUE_WHITE) == 6500  # white end
    assert cct_internal_to_kelvin(0, MIST_BW) == 21000
    assert cct_internal_to_kelvin(100, MIST_BW) == 7000


def test_kelvin_is_clamped_to_device_range():
    assert kelvin_to_cct_internal(1000, STANDARD) == 0
    assert kelvin_to_cct_internal(9000, STANDARD) == 100
    assert kelvin_to_cct_internal(1000, BLUE_WHITE) == 100
    assert kelvin_to_cct_internal(30000, BLUE_WHITE) == 0
    assert cct_internal_to_kelvin(0, WARM) == 2700
    assert cct_internal_to_kelvin(100, WARM) == 7000


def test_default_kelvin_is_range_midpoint():
    assert default_kelvin(STANDARD) == 4750
    assert default_kelvin(WARM) == 4850
    assert default_kelvin(BLUE_WHITE) == 13500


# ── Time parsing ─────────────────────────────────────────────────────────────

def test_parse_time_accepts_seconds():
    assert parse_time("07:30:00") == (7, 30)
    assert parse_time("23:59") == (23, 59)


@pytest.mark.parametrize("bad", ["25:00", "12:60", "noon", "12"])
def test_parse_time_rejects_invalid(bad):
    with pytest.raises(ValueError):
        parse_time(bad)


# ── Timer list helpers ───────────────────────────────────────────────────────

def test_normalize_timer_list_pads_and_copies():
    raw = [{"active": True}]
    timers = normalize_timer_list(raw)
    assert len(timers) == 5
    assert timers[1:] == [{"active": False}] * 4
    timers[0]["active"] = False
    assert raw[0]["active"] is True  # The stored options must not be mutated.


def test_compact_timers_fills_slots_from_one_like_the_app():
    off = {"active": False}
    second = {"active": True, "start": "08:00"}
    fourth = {"active": True, "start": "18:00"}
    assert compact_timers([off, second, off, fourth, off]) == [second, fourth, off, off, off]
    assert compact_timers([off] * 5) == [off] * 5


def test_relabel_timer_kelvin_keeps_device_value():
    # A blue-white timer saved under the old 3000-6500 K labels.
    old = [{"active": True, "cct_internal": 0, "color_temp_kelvin": 3000}, {"active": False}]
    new = relabel_timer_kelvin(old, BLUE_WHITE)
    assert new[0] == {"active": True, "cct_internal": 0, "color_temp_kelvin": 20500}
    assert new[1] == {"active": False}
    assert old[0]["color_temp_kelvin"] == 3000  # input untouched
    assert relabel_timer_kelvin(new, BLUE_WHITE) is None  # already up to date
