
# ONF Light — Home Assistant Integration

![logo](custom_components\onf_light\brand\dark_logo.png)

Custom integration to control ONF Bluetooth lights (reverse-engineered from the official Android app). Provides brightness and CCT control for supported ONF models via Bluetooth Low Energy (Nordic UART).

This project implements the same protocol and device-specific behavior observed in the official ONF app, including model-aware CCT ranges, debounce & optimistic updates, and a hybrid BLE connection strategy for reliable control.

**Supported:** ONF BLE lights (various models — brightness-only and tunable white models). Tested on MIST O+ only.

**Warning:** This integration communicates directly with Bluetooth devices; it requires a Home Assistant host with a working Bluetooth adapter and the appropriate OS-level Bluetooth permissions.

---

## Features

- Brightness control
- Color temperature (CCT) control exposed as Kelvin-based attribute
- Model-aware behavior (brightness-only models handled correctly)
- Optimistic updates, debounce, and readback confirmation to reduce UI bounce
- Hybrid BLE connection (persistent with idle timeout) and per-command retries
- Automatic discovery via Home Assistant Bluetooth when available

## Requirements

- Home Assistant with Bluetooth support (Linux with bluez, macOS, or a supported Bluetooth adapter)
- Python 3.10+ (in line with Home Assistant core requirements)

## Installation

Manual install (HACS or custom components):

1. Copy the `custom_components/onf_light` folder into your Home Assistant `config` directory under `custom_components`.
2. Restart Home Assistant.
3. Configure via Integrations UI or add a config entry.

## Installation Using HACS

HACS is a popular Home Assistant Community Store. To install this integration using HACS:

1. In Home Assistant, HACS → 3-dot menu → Custom repositories.
2. Add the repository URL. Use `integration` as the category.
3. Search for "ONF Light" in HACS and click "Install".
4. After adding, reboot Home Assistant.
5. Go to Settings → Integrations, If there is a ONF device nearby, you should see a notification to set up the ONF Light integration. Follow the prompts to complete the setusp.

## Usage

- Brightness: standard Home Assistant light brightness (0-255) mapping is used.
- Color temperature: exposed as `color_temp_kelvin` (Kelvin). The integration maps Kelvin to the device's internal integer steps and quantizes values for models that require it.

Notes:

- Some ONF models are brightness-only; the integration will present only supported controls for those devices.
- After sending changes the integration performs a short readback to confirm device state and suppress stale-state bounce.

## Troubleshooting

- Device becomes unavailable: ensure the Home Assistant host's Bluetooth adapter is enabled and within range. Reload the integration if necessary.
- Changes not applying: check Home Assistant logs for BLE communication errors. Ensure the device is powered on and not connected to another app.

## Credits

- Reverse engineering based on decompiled ONF Android app resources using JADX.
