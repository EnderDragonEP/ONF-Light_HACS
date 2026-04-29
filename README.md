# ONF Light — Home Assistant Integration

[English](README.md) | [中文](README_zh.md)

![logo](custom_components/onf_light/brand/dark_logo.png)

Custom integration to control ONF Bluetooth plant lights (reverse-engineered from the official Android app). Provides brightness and CCT control for supported ONF models via Bluetooth Low Energy (Nordic UART).

This project implements the same protocol and device-specific behavior observed in the official ONF app, including model-aware CCT ranges, debounce & optimistic updates, a hybrid BLE connection strategy, on-device scheduling, and automatic clock synchronization.

**Supported:** ONF BLE lights (various models — brightness-only and tunable white). Tested on MIST O+.

**Warning:** This integration communicates directly with Bluetooth devices. It requires a Home Assistant host with a working Bluetooth adapter and appropriate OS-level Bluetooth permissions.

**Note:** Manually controlling the light — either through HA or the official app — switches the device into manual mode and disables the active schedule. To resume scheduled operation, re-push the schedules by saving the options form (gear icon) or re-enabling them in the official app.

---

## Features

- Brightness and color temperature (CCT) control via Kelvin-based attribute
- Model-aware behavior — brightness-only models handled correctly
- Optimistic updates, debounce, and readback confirmation to reduce UI bounce
- Hybrid BLE connection with configurable idle timeout and per-command retries
- Polling backoff when device is unreachable — reduces unnecessary BLE traffic
- Automatic device discovery via Home Assistant Bluetooth

### On-device scheduling

Up to 5 automatic lighting schedules can be stored directly on the device and run from its internal real-time clock. **No active Bluetooth connection is required while a schedule is running.** Schedules survive power loss once the device clock is synced.

Schedules can be configured through the integration's options UI (gear icon) or via HA services.

### Device time synchronization

The integration automatically syncs the device's internal clock to your Home Assistant time on first connect, then repeats on a configurable interval (default: 24 hours). A **Sync Device Clock** button entity is also available for manual syncs.

Without clock sync, on-device timers may drift or fire at incorrect times after power loss.

### Connection management

The integration's options UI exposes three connection settings:

| Setting | Default | Description |
|---|---|---|
| State Poll Interval | 10 s | How often HA polls device state in the background. Set to 0 to disable polling (HA updates only after sending a command). Setting above your idle disconnect value allows the device to disconnect between polls — useful for app coexistence. |
| BLE Idle Disconnect | 30 s | Seconds of inactivity before HA drops the BLE connection. Set to -1 to keep permanently connected. |
| Clock Sync Interval | 1440 min | How often to automatically sync the device clock. Set to 0 to disable. |

### Diagnostic entities

The following diagnostic entities are attached to the device:

| Entity | Type | Default | Description |
|---|---|---|---|
| Bluetooth Connection | Binary sensor | Enabled | Live BLE connection state — updates immediately on connect/disconnect |
| Active Timers | Sensor | Enabled | Number of active schedule slots (0–5), with per-slot details as attributes |
| Firmware Version | Sensor | Disabled | Device firmware string (e.g. `R09A`), fetched once on first connect |
| Signal Strength | Sensor | Disabled | Last advertised RSSI in dBm |
| Color Temperature Range | Sensor | Disabled | Supported Kelvin range (e.g. `2700K – 7000K`) or `Brightness Only` |

Disabled-by-default entities can be enabled individually in the entity registry.

### HA Services

| Service | Description |
|---|---|
| `onf_light.set_timer` | Set a timer slot (slot 1–5, start time, end time, brightness, optional color temperature) |
| `onf_light.clear_timer` | Clear one slot by number, or omit slot to clear all |

---

## Requirements

- Home Assistant with Bluetooth support (Linux with BlueZ, macOS, or a supported Bluetooth adapter)
- Python 3.10+ (in line with Home Assistant core requirements)

---

## Installation via HACS

1. In Home Assistant, go to HACS → 3-dot menu → Custom repositories.
2. Add this repository URL. Set category to `Integration`.
3. Search for "ONF Light" in HACS and click **Install**.
4. Restart Home Assistant.
5. Go to **Settings → Integrations**. If an ONF device is nearby, a discovery notification will appear. Follow the prompts to complete setup.

## Manual Installation

1. Copy the `custom_components/onf_light` folder into your Home Assistant `config/custom_components` directory.
2. Restart Home Assistant.
3. Go to **Settings → Integrations → Add Integration** and search for ONF Light.

---

## Usage

### Brightness and color temperature

Standard HA light controls. Brightness uses the 0–255 HA scale. Color temperature is exposed as `color_temp_kelvin` and mapped to the device's internal step granularity automatically.

### Timer schedules

Open the integration's gear icon (⚙) in **Settings → Integrations** to configure up to 5 timer slots. Each slot has an on time, off time, brightness, and (for CCT devices) a color temperature. Schedules are pushed to the device and run from its internal clock — they continue to operate even when HA is offline.

---

## Troubleshooting

- **Device becomes unavailable:** Ensure the Bluetooth adapter is enabled and within range. The integration automatically backs off polling when the device is unreachable. Reload the integration if needed.
- **Changes not applying:** Check Home Assistant logs for BLE communication errors. Ensure the device is powered on and not exclusively connected to another app. Raising the poll interval above the idle disconnect value allows the app to use the device between polls.
- **Timers not firing at the right time:** Use the Sync Device Clock button to manually resync the device RTC. The integration syncs automatically on connect, but the device clock may drift after extended power loss.

---

## Credits

- Reverse engineering based on decompiled ONF Android app resources using JADX.
- Claude Sonnet 4.6 used for AI-accelerated development.
