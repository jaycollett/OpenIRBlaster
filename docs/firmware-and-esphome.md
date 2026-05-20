# Firmware & ESPHome

This page covers firmware installation and ESPHome configuration for OpenIRBlaster devices, including the requirements for integration compatibility.

---

## Firmware Installation

### Option 1: Pre-built Binary (Easiest)

A pre-compiled binary is available for ESP8266 devices. No build tools required.

1. Download `factory_flash.bin` from [releases](https://github.com/jaycollett/OpenIRBlaster/releases)
2. Flash using [ESPHome Web Flasher](https://web.esphome.io/) or esptool:
   ```bash
   esptool.py write_flash 0x0 factory_flash.bin
   ```
3. Connect to "OpenIRBlaster Setup" WiFi hotspot and configure your network
4. The device will appear in Home Assistant's ESPHome integration for adoption

### Option 2: Build from ESPHome YAML

If you prefer to compile the firmware yourself or want to customize it:

1. Copy `hardware/firmware/factory_flash.yaml` to your ESPHome dashboard
2. Compile and flash to your ESP device
3. Connect to "OpenIRBlaster Setup" WiFi and configure your network

This option is useful if you want to:
- Customize the firmware (add sensors, change pins, etc.)
- Use an ESP32 instead of ESP8266
- Include additional ESPHome components

### First-Time USB Flash

For new devices without existing firmware, connect via USB and run:

```bash
esphome run factory_flash.yaml --device /dev/ttyUSB0
```

---

## Firmware Requirements for Integration Compatibility

The Home Assistant integration relies on specific firmware components to function correctly. If you're customizing the firmware or building your own hardware, these elements are **required**.

### 1. Project Block (Device Discovery)

The integration discovers devices by checking the ESPHome project metadata. This block is **required**:

```yaml
esphome:
  name: ${name}
  project:
    name: "jaycollett.openirblaster"
    version: "0.5.0"
```

The integration filters devices where `manufacturer == "jaycollett"` and `model == "openirblaster"`. Without this, your device won't appear in the integration's device picker.

### 2. Learning Mode Switch

The integration toggles this switch to enable/disable IR learning:

```yaml
switch:
  - platform: template
    name: "IR Learning Mode"
    id: ir_learning_mode
    restore_mode: ALWAYS_OFF
    optimistic: true
    turn_on_action:
      - lambda: "id(learn_enabled) = true;"
    turn_off_action:
      - lambda: "id(learn_enabled) = false;"
```

This creates the entity `switch.<device>_ir_learning_mode` that the integration controls.

### 3. ESPHome API Services

The integration calls two services on the device. Both must be present:

```yaml
api:
  services:
    - service: send_ir_raw
      variables:
        carrier_hz: int
        code: int[]
      then:
        - remote_transmitter.transmit_raw:
            transmitter_id: ir_tx
            carrier_frequency: !lambda "return (float)carrier_hz;"
            code: !lambda "return code;"

    - service: replay_last_ir
      then:
        - if:
            condition:
              lambda: "return !id(last_pulses_json).empty();"
            then:
              - homeassistant.event:
                  event: esphome.openirblaster_learned
                  data:
                    # Same six fields as the learned event below, sourced
                    # from the cached globals so a replay carries identical
                    # data to the original capture.
                    ...
```

`send_ir_raw` becomes `esphome.<device>_send_ir_raw` and is used for every IR transmission. `replay_last_ir` becomes `esphome.<device>_replay_last_ir` and is called by the integration only as a recovery path when the marker text_sensor changed but the learned event was lost on a dropped API socket.

### 4. MAC Address Sensor

The integration reads the MAC address during setup for stable device identification. The `id:` is required because the on_raw lambda reads from `.state` rather than `WiFi.macAddress().c_str()`:

```yaml
text_sensor:
  - platform: wifi_info
    mac_address:
      name: "MAC Address"
      id: text_sensor_mac_address
```

Why the `id`: `WiFi.macAddress()` returns a temporary Arduino `String` whose buffer is freed at the end of the lambda's return statement. ESPHome's templating wrapper then copies a freed pointer into the protobuf field, which HA rejects as invalid UTF-8 and drops the event. Reading from a stable `std::string` member on the wifi_info text_sensor avoids that lifetime hazard.

### 5. Capture Globals

The on_raw handler caches the most recent capture so the `replay_last_ir` service can re-fire the event with identical data. Required globals:

```yaml
globals:
  - id: learn_enabled
    type: bool
    restore_value: no
    initial_value: "false"
  - id: last_pulses_json
    type: std::string
    restore_value: no
  - id: last_carrier_hz
    type: int
    restore_value: no
    initial_value: "0"
  - id: last_timestamp
    type: std::string
    restore_value: no
  - id: last_rssi
    type: int
    restore_value: no
    initial_value: "0"
```

### 6. Capture Marker Text Sensor

A small text_sensor whose state is just the timestamp of the most recent learned capture. The state replays on API reconnect, so the integration can detect a dropped event by watching for state changes:

```yaml
text_sensor:
  - platform: template
    name: "Last IR Capture Marker"
    id: last_ir_capture_marker
    update_interval: never
```

### 7. Learned Code Event

When an IR code is received during learning mode, the firmware must fire this Home Assistant event:

```yaml
homeassistant.event:
  event: esphome.openirblaster_learned
  data:
    device_id: !lambda "return App.get_name();"
    mac_address: !lambda "return id(text_sensor_mac_address).state;"
    carrier_hz: !lambda "return id(last_carrier_hz);"
    pulses_json: !lambda "return id(last_pulses_json);"
    timestamp: !lambda "return id(last_timestamp);"
    rssi: !lambda "return id(last_rssi);"
```

The pattern is: build the capture into globals first (in a lambda earlier in the action list), then fire the event reading from globals. Both the initial event and any `replay_last_ir` call read from the same globals, so the replay carries identical data.

**Event Fields:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `device_id` | string | Yes | ESPHome device name (e.g., "openirblaster-2ca965") |
| `mac_address` | string | **Recommended** | Device MAC address for stable identification |
| `carrier_hz` | int | Yes | IR carrier frequency (typically 38000) |
| `pulses_json` | string | Yes | JSON array of pulse timings in microseconds |
| `timestamp` | string | No | ISO 8601 timestamp (defaults to current time if omitted) |
| `rssi` | int | No | WiFi RSSI at capture time (diagnostic only) |

---

## Why MAC Address Matters

Prior to firmware v0.4.0, the integration identified devices solely by their ESPHome device name (e.g., `openirblaster-2ca965`). This caused problems when users modified their ESPHome YAML:

- Adding components (like `web_server:`) could trigger ESPHome to re-register the device
- This sometimes created duplicate device entries in Home Assistant
- Users had to manually clean up orphaned devices

**The fix:** The integration now uses the device's MAC address as the primary identifier. Since the MAC address is tied to the hardware and never changes, the integration can reliably identify the same physical device even after firmware updates or ESPHome configuration changes.

**Firmware requirements for stable identification:**

1. Include `mac_address` in the `esphome.openirblaster_learned` event
2. Expose the MAC Address sensor via `wifi_info`

Both are included in the factory firmware v0.4.0+. Firmware v0.5.0 additionally adds the `replay_last_ir` service and the small capture-marker text_sensor so the integration can recover from a dropped event on a transient API disconnect.

---

## Configuration Options

### Device Naming

The factory firmware uses `name_add_mac_suffix: true` to ensure unique device names:

```yaml
esphome:
  name: openirblaster
  name_add_mac_suffix: true  # Results in "openirblaster-2ca965"
```

If you're configuring an existing device (already has a name with MAC suffix), set:

```yaml
esphome:
  name: openirblaster-2ca965  # Your specific device name
  name_add_mac_suffix: false
```

### IR Carrier Frequency

The default carrier frequency is 38kHz, which works for most devices. To change it:

```yaml
substitutions:
  default_carrier_hz: "36000"  # For 36kHz devices
```

### IR Buffer Size

For complex IR codes, you may need to increase the buffer:

```yaml
remote_receiver:
  buffer_size: 6kb  # Default, increase if codes are truncated
```

---

## Customization

### Adding Your Own Components

You can safely add additional ESPHome components without breaking integration compatibility. For example:

```yaml
# Web server for local debugging
web_server:
  port: 80

# Additional sensors
sensor:
  - platform: dht
    pin: GPIO4
    temperature:
      name: "Temperature"
```

Just ensure the required components (project block, learning switch, send service, learned event, MAC sensor) remain intact.

### Using Your Own Project Name

If you want to use this integration with your own hardware project, you have two options:

1. **Use the OpenIRBlaster project name** in your firmware:
   ```yaml
   project:
     name: "jaycollett.openirblaster"
   ```

2. **Fork the integration** and modify the device discovery filter in `config_flow.py` to match your project name.

---

## Firmware Versions

| Version | Changes |
|---------|---------|
| 0.5.0 | Fixed dangling-pointer in MAC address lambda. Added `replay_last_ir` service and capture-marker text_sensor for event-loss recovery |
| 0.4.0 | Added MAC address to learned event for stable device identification |
| 0.3.0 | Initial public release |

---

## Troubleshooting

### Device not appearing in integration setup

- Verify the `project.name` is exactly `"jaycollett.openirblaster"`
- Ensure the device is online and connected to Home Assistant via ESPHome
- Check that the MAC Address sensor is exposed and has a valid state

### Duplicate devices appearing

- Update to firmware v0.4.0+ which includes MAC address identification
- Remove duplicate devices from Home Assistant
- Re-add the device to the integration

### IR codes not being learned

- Check that the Learning Mode switch exists and is controllable
- Verify the `esphome.openirblaster_learned` event is being fired (check HA Developer Tools > Events)
- Ensure the IR receiver is wired correctly (GPIO5 for TSOP38238)

See the [Troubleshooting](troubleshooting.md) page for more solutions.
