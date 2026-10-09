# Changelog

## 1.2.0

This release compares the integration with the official ONF Link app (version 2.5.1) and makes it behave the same way. It also fixes several Bluetooth connection problems.

### ⚠️ Please read before updating

**Blue-white models now use the app's colour temperature scale.** This affects ONF-1S, ONF-1P, ONF-1S+, ONF-1P+, ONF-3S+, ONF-3P+, FLAT NANO+ BW and MIST O+ BW.

- Before this release, these lights showed 3000–6500 K in Home Assistant, and the scale ran the wrong way. Choosing a warm colour actually made the light fully blue.
- The range now matches the ONF Link app: 6500 K (white) to 20500 K (blue). On the MIST O+ BW it is 7000 K to 21000 K.
- **If you have automations or scenes that set a colour temperature on one of these lights, check them and pick new values.** The old numbers will now give a different colour.
- Saved timer schedules are not affected. The light keeps doing exactly what it did before, and only the Kelvin number shown in Home Assistant changes.

Other tunable-white models and brightness-only models are unchanged.

### Timer schedules

- **Schedules now show up in the ONF Link app.** Enabled slots are written to the light in order with no gaps, the same way the app does it. For example, if you only enable slots 2 and 4, the light stores them as its first and second timers.
- **Brightness-only models use the app's current timer commands.** This covers FLAT NANO+, FLAT NANO++, FLAT NANO+ S, MIST O+ W and MIST O+ S. Each slot's start time is now used as you set it.
- **Schedules saved while the light is out of range are no longer lost.** The schedule is kept and sent automatically the next time Home Assistant reaches the light. This also applies when you clear timers while the light is offline.
- **The Set Timer and Clear Timer actions report an error** when the light can't be reached, instead of appearing to succeed.
- **The Set Timer action rejects invalid times** such as 25:00. When you leave out the colour temperature, it now uses the middle of the light's range, like the settings dialog.
- **The settings dialog closes right away** when you save. The schedule is sent in the background.

### Bluetooth connection fixes

- **The idle disconnect now really disconnects.** Previously the connection stayed open after the idle timeout, which could stop the ONF Link app from connecting and could use up a Bluetooth proxy slot.
- **Connections are more reliable, especially through ESPHome Bluetooth proxies.** The integration now connects the way Home Assistant recommends, with automatic retries.
- **The Bluetooth Connection sensor updates immediately** when the light goes out of range.
- **Turning a light off no longer hangs** when the light is unreachable. The action returns right away, just like turning on.
- **Dragging a brightness or colour slider quickly** now always ends on the last value you chose.
- **Less Bluetooth traffic.** The light was being polled twice, once by the integration and once by Home Assistant. It is now polled only on the interval you set in the options.
- **An idle disconnect of 0 seconds** now disconnects right after each command, as the setting describes. Before, it waited about 5 seconds.

### Other fixes

- **Device clock sync now uses Home Assistant's time zone.** Docker installs often run in UTC, which could make on-device schedules fire hours early or late.
- **Timer and clock commands now wait for the light to confirm them**, as the app does. This prevents occasional false "unavailable" states and log warnings right after saving a schedule.
- **The Sync Device Clock button shows an error** when the light can't be reached.
- **The firmware version and clock sync are retried automatically** if they fail on the first connection.
- **The light's state is read as soon as Home Assistant starts**, instead of after the first poll interval.
- **Diagnostic sensors show values immediately at startup**, instead of being empty for the first 30 seconds.
- **The high-resolution integration icon now displays correctly.**

### Requirements

The minimum Home Assistant version is still 2024.12.0. No configuration changes are needed.

## 1.1.0

Earlier release. See the [commit history](https://github.com/EnderDragonEP/ONF-Light_HACS/commits/main) for details.
