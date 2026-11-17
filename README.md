# Hive Schedule Manager

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)

A Home Assistant custom integration for managing Hive UK heating schedules. Set heating schedules for any day of the week using pre-defined profiles or custom time/temperature setpoints — all from Home Assistant automations and scripts.

## Features

- Full SMS MFA authentication with automatic device confirmation
- Automatic token refresh — enter your MFA code once during setup, never again
- Set heating schedules per day via HA service calls
- 8 built-in schedule profiles (workday, weekend, WFH, holiday, etc.)
- Profiles loaded from `hive_schedule_profiles.yaml` at runtime — edits take effect without restart (file is auto-created on first run)
- Custom time/temperature schedule support
- HACS compatible

## Installation

### HACS (recommended)

1. In HA, go to **HACS → Integrations → ⋮ → Custom repositories**
2. Add this repository URL, category: **Integration**
3. Install **Hive Schedule Manager**
4. Restart Home Assistant

### Manual

Copy `custom_components/hive_schedule_manager/` to your HA `custom_components/` directory and restart.

## Setup

1. Go to **Settings → Devices & Services → Add Integration**
2. Search for **Hive Schedule Manager**
3. Enter your Hive account email and password
4. Enter the SMS verification code sent to your phone
5. Done — the integration confirms your device automatically and will refresh tokens indefinitely

## Services

### `hive_schedule_manager.set_day_schedule`

Update the heating schedule for a specific day.

```yaml
service: hive_schedule_manager.set_day_schedule
data:
  node_id: "a1b2c3d4-e5f6-7890-abcd-ef1234567890"   # thermostat node ID
  day: monday
  profile: workday    # OR use 'schedule' for custom setpoints
```

**Built-in profiles**: `workday`, `weekend`, `nonworkday`, `holiday`, `all_day_comfort`, `wfh`, `custom1`, `custom2`

**Custom schedule**:

```yaml
service: hive_schedule_manager.set_day_schedule
data:
  node_id: "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
  day: saturday
  schedule:
    - time: "07:30"
      temp: 19.0
    - time: "22:00"
      temp: 16.0
```

### `hive_schedule_manager.refresh_token`

Manually trigger a token refresh (normally automatic).

## Schedule Profiles File

Profiles are loaded from `hive_schedule_profiles.yaml` in your Home Assistant config directory at runtime. On first load, if the file does not exist it is created automatically by seeding it from the built-in defaults. Once the file exists it is read on every `set_day_schedule` call, so edits take effect immediately without restarting Home Assistant.

The seasonal toggle (`input_boolean.heating_winter_summer`) controls which profile set is active by copying `hive_schedule_profiles_winter.yaml` or `hive_schedule_profiles_summer.yaml` over `hive_schedule_profiles.yaml` via the `"Heating: Sync Seasonal Profiles"` automation.

## Finding Your Node ID

The thermostat node ID can be found in the Hive web app URL when viewing your thermostat, or by examining the Home Assistant logs at startup (the integration logs discovered nodes).

## Technical Details

For a deep-dive into how the authentication works, the Cognito SRP flow, device tracking, and the Hive API format see [README_DETAIL.md](README_DETAIL.md).

## Requirements

- Hive UK account with SMS MFA enabled
- Home Assistant 2024.1.0 or later

## License

MIT
