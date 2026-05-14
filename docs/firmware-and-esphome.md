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
    version: "0.4.0"
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

### 3. IR Send Service

The integration calls this service to transmit IR codes:

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
```

This creates the service `esphome.<device>_send_ir_raw`.

### 4. Learned Code Event

When an IR code is received during learning mode, the firmware must fire this Home Assistant event:

```yaml
homeassistant.event:
  event: esphome.openirblaster_learned
  data:
    device_id: !lambda "return App.get_name();"
    mac_address: !lambda "return WiFi.macAddress().c_str();"
    carrier_hz: !lambda "return 38000;"
    pulses_json: !lambda |-
      // JSON array of pulse timings
      std::string s = "[";
      for (size_t i = 0; i < x.size(); i++) {
        s += to_string((int) x[i]);
        if (i + 1 < x.size()) s += ",";
      }
      s += "]";
      return s;
    timestamp: !lambda |-
      auto now = id(ha_time).now();
      if (now.is_valid()) return now.strftime("%Y-%m-%dT%H:%M:%S%z");
      return std::string("");
```

**Event Fields:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `device_id` | string | Yes | ESPHome device name (e.g., "openirblaster-2ca965") |
| `mac_address` | string | **Recommended** | Device MAC address for stable identification |
| `carrier_hz` | int | Yes | IR carrier frequency (typically 38000) |
| `pulses_json` | string | Yes | JSON array of pulse timings in microseconds |
| `timestamp` | string | No | ISO 8601 timestamp (defaults to current time if omitted) |

### 5. MAC Address Sensor

The integration reads the MAC address during setup for stable device identification:

```yaml
text_sensor:
  - platform: wifi_info
    mac_address:
      name: "MAC Address"
```

This is **critical** for preventing duplicate devices when ESPHome configuration changes (see below).

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

Both are included in the factory firmware v0.4.0+.

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
