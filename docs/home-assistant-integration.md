# Home Assistant Integration

This page covers setting up and using the OpenIRBlaster integration with Home Assistant (integration v1.2.x, HA 2024.12 or later).

## Installation

### HACS (Recommended)

1. Open HACS in your Home Assistant instance
2. Click on **Integrations**
3. Click the **+ Explore & Download Repositories** button
4. Search for "OpenIRBlaster"
5. Click **Download**
6. Restart Home Assistant

### Manual Installation

1. Download the [latest release](https://github.com/jaycollett/OpenIRBlaster/releases)
2. Extract and copy the `custom_components/openirblaster` folder to your Home Assistant `custom_components` directory
3. Restart Home Assistant

## Setup

1. Navigate to **Settings** → **Devices & Services**
2. Click **+ Add Integration**
3. Search for "OpenIRBlaster"
4. Select your ESPHome OpenIRBlaster device from the dropdown
5. Click **Submit**

If you later rename the device in ESPHome, you do not need to remove and re-add the integration - see [Reconfiguring After an ESPHome Rename](#reconfiguring-after-an-esphome-rename).

## Entities and Device Layout

Each blaster is a single device in Home Assistant. Its entities are grouped by section on the device page:

### Controls (main section)
- **{Your Code Names}** - one button per saved code; press to transmit
- **Code Activity** - an event entity that records every capture and save (see [Automating on Code Activity](#automating-on-the-code-activity-event))

### Configuration
- **Code Name** - text field: the name for the next code you learn
- **Learn IR Code** - button: arms learning mode
- **Send Last Learned** - button: replays the most recently captured code (handy for testing before you save)

### Diagnostic
- **Last Learned Code Name** - name of the most recently saved code
- **Last Learned Timestamp** - when the last code was captured
- **Last Learned Pulse Count** - size of the last code (for debugging)

> Upgrading from an older version? The separate "Controls" device is gone; its entities now live on the main device under Configuration. The migration happens automatically at startup.

## Adding a Code

### From the UI (recommended)

1. On the device page, type a name into the **Code Name** field (e.g., "TV Power")
2. Press **Learn IR Code**
3. Within 30 seconds, hold your remote 2-6 inches from the IR receiver and press the button you want to capture
4. A "Code Learned" notification appears, the new code button shows up immediately (no restart or reload needed), and the Code Name field clears itself

Notes on this flow:

- **Timeout:** if no signal arrives within 30 seconds, learning stops, the device's learning mode is switched off, and a "Learning Timed Out" notification appears. Just press **Learn IR Code** again to retry.
- **Duplicate names:** if the name already exists, a "Duplicate Name" notification appears and nothing is saved - pick a different name and learn again.
- **Empty name:** pressing **Learn IR Code** with an empty Code Name shows a "Name Required" notification and does not arm learning.
- **Garbled capture:** if the device receives something it cannot validate, a "Learning Cancelled" notification appears with the reason.

If the integration doesn't pick up the learned code even though ESPHome logs show the IR signal arrived, see [Troubleshooting](troubleshooting.md#ir-receiver-not-learning-codes). As a last resort, codes can be added manually to the storage file - see [Storage Format & Manual Editing](storage-format.md).

### Captured without a name? Use the save form

If a code was captured without a pre-typed name (for example, armed via the `learn_start` service), the capture is held as a *pending* code:

1. Go to **Settings** → **Devices & Services** → **OpenIRBlaster**
2. Click **Configure** on the device
3. The save form opens automatically while a code is pending: enter a **name** (plus optional **tags** and **notes**) and submit

You can also press **Send Last Learned** first to test the pending code before saving it.

### From scripts and automations

`learn_start` arms a learning session. With a response variable, the call waits for the outcome and hands the capture metadata back to your script:

```yaml
action: openirblaster.learn_start
data:
  config_entry_id: "01KESZQ4GF6WSK5XBAA19N96MM"
  timeout: 60
response_variable: capture
```

The response contains `status` (`received`, `timeout`, or `cancelled`) and, on success, `carrier_hz`, `pulse_count`, and `timestamp`. Without `response_variable` the call returns immediately (fire and forget).

After a successful capture, save the pending code with `save_pending`:

```yaml
action: openirblaster.save_pending
data:
  config_entry_id: "01KESZQ4GF6WSK5XBAA19N96MM"
  name: "TV Power"
  tags: "tv, living-room"
  notes: "Samsung TV power toggle"
response_variable: saved   # optional: {code_id, name, carrier_hz, pulse_count}
```

To abort a session, use `learn_cancel`. It refuses to throw away an unsaved capture unless you say so:

```yaml
action: openirblaster.learn_cancel
data:
  config_entry_id: "01KESZQ4GF6WSK5XBAA19N96MM"
  discard_pending: true   # omit (default false) to protect a pending code
```

The `config_entry_id` for all services can be picked from a dropdown in the UI service editor, or found in the URL of the integration page.

## Renaming a Code

```yaml
action: openirblaster.rename_code
data:
  config_entry_id: "01KESZQ4GF6WSK5XBAA19N96MM"
  id: "tv_power"
  new_name: "Living Room TV Power"
```

The button's display name updates live. The code's `id` and the button's entity ID stay stable, so existing automations keep working.

## Deleting a Code

### From the UI

1. Go to **Settings** → **Devices & Services** → **OpenIRBlaster**
2. Click **Configure** on the device
3. Select **Manage IR Codes**
4. Pick the code from the dropdown
5. Confirm on the deletion screen

The button entity disappears immediately.

### From a service call

```yaml
action: openirblaster.delete_code
data:
  id: "tv_power"
  config_entry_id: "01KESZQ4GF6WSK5XBAA19N96MM"
```

`config_entry_id` is optional with a single blaster, but **required when more than one blaster has a code with the same id** - the service refuses to guess which one you meant.

## Sending Codes

Three ways to transmit:

1. **Code buttons** - press the button entity (or `button.press` it from an automation)
2. **Send Last Learned** - replays the current pending capture, for testing before saving
3. **The `send_code` service** - for scripts, including one-off sends of codes that are not stored:

```yaml
action: openirblaster.send_code
data:
  config_entry_id: "01KESZQ4GF6WSK5XBAA19N96MM"
  id: "tv_power"
response_variable: sent   # optional: {code_id, name, carrier_hz, pulse_count, sent: true}
```

`carrier_hz` and `pulses` can be supplied to override (or send without) a stored code.

## Automating on the Code Activity Event

The **Code Activity** event entity fires two event types:

- `code_learned` - a capture was finalized (attributes: `carrier_hz`, `pulse_count`, `timestamp`, and `rssi` when the firmware provides it)
- `code_saved` - a code was saved to the library (attributes: `code_id`, `name`, `carrier_hz`, `pulse_count`)

```yaml
automation:
  - alias: "Announce captured IR codes"
    trigger:
      - platform: state
        entity_id: event.openirblaster_code_activity
    condition:
      - condition: template
        value_template: "{{ trigger.to_state.attributes.event_type == 'code_learned' }}"
    action:
      - service: notify.mobile_app_phone
        data:
          message: >
            Captured an IR code:
            {{ trigger.to_state.attributes.pulse_count }} pulses at
            {{ trigger.to_state.attributes.carrier_hz }} Hz
```

## Automation Examples

### Turn off TV at bedtime

```yaml
automation:
  - alias: "Turn off TV at bedtime"
    trigger:
      - platform: time
        at: "23:00:00"
    action:
      - service: button.press
        target:
          entity_id: button.openirblaster_tv_power
```

### Voice Control

Use Home Assistant's voice assistants to trigger IR codes:

"Alexa, turn on the TV" -> Triggers IR code via automation

### Conditional Control

```yaml
automation:
  - alias: "Projector for movie time"
    trigger:
      - platform: state
        entity_id: media_player.living_room
        to: "playing"
    condition:
      - condition: state
        entity_id: input_boolean.movie_mode
        state: "on"
    action:
      - service: button.press
        target:
          entity_id: button.openirblaster_projector_power
```

Button entity IDs derive from your device name plus the code name; check the device page for the exact IDs on your install.

## Reconfiguring After an ESPHome Rename

If you rename the device in ESPHome, the integration's stored service binding goes stale. Instead of removing and re-adding:

1. Go to **Settings** → **Devices & Services** → **OpenIRBlaster**
2. Open the entry's menu (three dots) and choose **Reconfigure**
3. Select the (renamed) device and submit

The hardware identity is verified by MAC address: selecting a *different* blaster aborts with "wrong device" (your code library stays bound to its original hardware), and a device whose MAC sensor is unavailable aborts with a distinct message asking you to bring it fully online first.

## Repairs

The integration raises issues under **Settings** → **System** → **Repairs** for conditions you can act on:

| Issue | Meaning | Fix |
|-------|---------|-----|
| Firmware needs an update | The device sends a corrupted MAC in learned-code events (a bug in old firmware). Learning still works via name matching. | Update the device firmware |
| Could not identify the MAC address | Several ESPHome devices match this entry's name, so the MAC could not be back-filled unambiguously. | Run **Reconfigure** and pick the correct device |
| Cannot send IR codes | The ESPHome send service disappeared after setup (device offline or renamed). | Bring the device online, then reload or reconfigure |

Each issue clears automatically once the condition is resolved.

## Startup Housekeeping

On every startup the integration tidies up after older versions (all idempotent, no action needed):

- migrates entities off the legacy "Controls" device and removes it
- removes orphaned entity registry entries left by removed features (v1.2.1), such as the old per-code delete buttons
- back-fills the device's MAC address into entries created before MAC capture existed
- turns the device's learning mode off if a previous run was interrupted mid-session

## Storage

Learned codes are stored in `.storage/openirblaster_{entry_id}.json` and include:
- Display name
- Unique ID (slugified)
- Carrier frequency (typically 38kHz)
- Pulse timing array
- Timestamp

For the full schema and a safe procedure for editing the file by hand, see [Storage Format & Manual Editing](storage-format.md).

---

*See [Troubleshooting](troubleshooting.md) for common issues and solutions.*
