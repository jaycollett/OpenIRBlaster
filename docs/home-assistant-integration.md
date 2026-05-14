# Home Assistant Integration

This page covers setting up and using the OpenIRBlaster integration with Home Assistant.

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

## Entities Created

For each OpenIRBlaster device, you'll get:

### Text Input
- **Code Name** - Enter the name for the next IR code to learn

### Buttons
- **Learn IR Code** - Start learning mode (after entering a code name)
- **Send Last Learned** - Replay the most recently learned code
- **{Your Code Names}** - One button for each saved code

### Sensors
- **Last Learned Code Name** - Name of the most recent code
- **Last Learned Timestamp** - When the last code was captured
- **Last Learned Pulse Count** - Size of the last code (for debugging)

## Learning IR Codes

1. In your device's entity list, find the **Code Name** text field
2. Enter a name for the code you want to learn (e.g., "TV Power")
3. Click the **Learn IR Code** button
4. Within 30 seconds, point your remote at the IR receiver and press the button
5. A new button entity will automatically appear with your code name

If the integration doesn't pick up the learned code even though ESPHome logs show the IR signal arrived, see [Troubleshooting](troubleshooting.md#ir-receiver-not-learning-codes). As a last resort, codes can be added manually to the storage file - see [Storage Format & Manual Editing](storage-format.md).

## Deleting Codes

1. Go to **Settings** → **Devices & Services** → **OpenIRBlaster**
2. Click **Configure** on the device
3. Select **Manage IR Codes**
4. Pick a code and confirm deletion

## Services

The integration provides services for automation and scripting:

### `openirblaster.send_code`
Send a stored IR code programmatically.

```yaml
service: openirblaster.send_code
data:
  config_entry_id: "01KESZQ4GF6WSK5XBAA19N96MM"
  code_id: "tv_power"
```

### `openirblaster.rename_code`
Rename a stored code.

```yaml
service: openirblaster.rename_code
data:
  config_entry_id: "01KESZQ4GF6WSK5XBAA19N96MM"
  code_id: "tv_power"
  new_name: "Living Room TV Power"
```

### `openirblaster.delete_code`
Delete a stored code.

```yaml
service: openirblaster.delete_code
data:
  config_entry_id: "01KESZQ4GF6WSK5XBAA19N96MM"
  code_id: "tv_power"
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
