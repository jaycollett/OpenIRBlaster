# OpenIRBlaster for Home Assistant

A Home Assistant custom integration that lets you learn, store, and replay infrared remote control codes using ESPHome devices.

[![GitHub Release][releases-shield]][releases]
[![License][license-shield]](LICENSE)
[![hacs][hacsbadge]][hacs]

## What Does It Do?

Turn any ESPHome device with an IR receiver and transmitter into a universal remote control for your smart home:

- **Learn** IR codes from any remote control
- **Store** unlimited codes with custom names
- **Replay** codes with a single button press or automation
- **Control** all your IR devices through Home Assistant

Perfect for controlling TVs, AC units, fans, projectors, and other infrared-controlled devices.

## Requirements

- Home Assistant 2024.1+ (Python 3.12+)
- ESPHome device with:
  - IR receiver (TSOP38238 or similar)
  - IR transmitter (LED + transistor)
  - OpenIRBlaster firmware installed

## Hardware Setup

### Recommended Hardware

- **ESP8266** (ESP-12E) or **ESP32**
- **IR Receiver**: TSOP38238 (GPIO4)
- **IR LED**: 950nm IR LED (GPIO14)
- **Transistor**: IRLML6344 or similar for LED driving

### Firmware Installation

1. Copy the ESPHome configuration from `hardware/firmware/factory_config.yaml`
2. Customize the WiFi settings and device name
3. Flash to your ESP device using ESPHome
4. Verify the device appears in Home Assistant's ESPHome integration

See the `hardware/` directory for circuit diagrams and detailed build instructions.

## Installation

### HACS (Recommended - Coming Soon)

_This integration will be available via HACS once submitted to the default repository._

### Manual Installation

1. Download the [latest release](https://github.com/jaycollett/OpenIRBlaster/releases)
2. Extract and copy the `custom_components/openirblaster` folder to your Home Assistant `custom_components` directory
3. Restart Home Assistant
4. Go to **Settings** → **Devices & Services** → **Add Integration**
5. Search for "OpenIRBlaster" and follow the setup wizard

## Quick Start Guide

### 1. Add the Integration

1. Navigate to **Settings** → **Devices & Services**
2. Click **+ Add Integration**
3. Search for "OpenIRBlaster"
4. Select your ESPHome device from the dropdown
5. Click **Submit**

The integration will automatically discover your ESPHome IR blaster device and set up the necessary entities.

### 2. Learn Your First IR Code

1. In your device's entity list, find the **Code Name** text field
2. Enter a name for the code you want to learn (e.g., "TV Power")
3. Click the **Learn IR Code** button
4. Within 30 seconds, point your remote at the IR receiver and press the button
5. A new button entity will automatically appear with your code name

That's it! You can now press the new button to transmit the IR code.

### 3. Use in Automations

```yaml
automation:
  - alias: "Turn off TV at bedtime"
    trigger:
      - platform: time
        at: "23:00:00"
    action:
      - service: button.press
        target:
          entity_id: button.openirblaster_64c999_tv_power
```

## Entities Created

For each OpenIRBlaster device, you'll get:

### Text Input
- **Code Name** - Enter the name for the next IR code to learn

### Buttons
- **Learn IR Code** - Start learning mode (after entering a code name)
- **Send Last Learned** - Replay the most recently learned code
- **{Your Code Names}** - One button for each saved code
- **Delete {Code Name}** - Remove a saved code

### Sensors
- **Last Learned Code Name** - Name of the most recent code
- **Last Learned Timestamp** - When the last code was captured
- **Last Learned Pulse Count** - Size of the last code (for debugging)

## Advanced Features

### Services

The integration provides services for automation and scripting:

#### `openirblaster.send_code`
Send a stored IR code programmatically.

```yaml
service: openirblaster.send_code
data:
  config_entry_id: "01KESZQ4GF6WSK5XBAA19N96MM"
  code_id: "tv_power"
```

#### `openirblaster.rename_code`
Rename a stored code.

```yaml
service: openirblaster.rename_code
data:
  config_entry_id: "01KESZQ4GF6WSK5XBAA19N96MM"
  code_id: "tv_power"
  new_name: "Living Room TV Power"
```

#### `openirblaster.delete_code`
Delete a stored code.

```yaml
service: openirblaster.delete_code
data:
  config_entry_id: "01KESZQ4GF6WSK5XBAA19N96MM"
  code_id: "tv_power"
```

### Storage

Learned codes are stored in `.storage/openirblaster_{entry_id}.json` and include:
- Display name
- Unique ID (slugified)
- Carrier frequency (typically 38kHz)
- Pulse timing array
- Timestamp

## Troubleshooting

### "Learning session timed out"

- **Solution**: Make sure you press the Learn button first, then press your remote within 30 seconds
- Check that your IR receiver is working (view ESPHome logs)
- Ensure your remote is pointed directly at the receiver

### "Please enter a name for the IR code"

- **Solution**: Enter a code name in the "Code Name" text field before pressing Learn

### Codes learned but don't transmit

- Check ESPHome logs when you press the send button
- Verify the IR LED is wired correctly (check hardware documentation)
- Try adjusting carrier frequency if needed (most remotes use 38kHz)
- Test with "Send Last Learned" button first

### Integration won't install

- Verify your ESPHome device is online and connected
- Check that the IR Learning Mode switch entity exists
- Restart Home Assistant and try again

## Example Use Cases

### Universal Remote Dashboard

Create a dashboard with all your IR device controls in one place.

### Voice Control

"Alexa, turn on the TV" → Triggers IR code via Home Assistant automation.

### Scheduled Actions

Automatically turn off your AC unit when you leave home or at a specific time.

### Conditional Control

Turn on your projector when movie time starts, turn it off when the movie ends.

## Development

Want to contribute? Check out:

- [`CLAUDE.md`](CLAUDE.md) - Development guidelines and architecture
- [`TESTING.md`](TESTING.md) - Testing instructions
- [`hardware/`](hardware/) - Hardware design files and documentation

```bash
# Setup development environment
git clone https://github.com/jaycollett/OpenIRBlaster.git
cd OpenIRBlaster
python3 -m venv venv
source venv/bin/activate
pip install -r requirements_dev.txt

# Run tests
pytest
```

## Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes with tests
4. Ensure all tests pass (`pytest`)
5. Submit a pull request

## Support

- **Issues**: [Report bugs or request features](https://github.com/jaycollett/OpenIRBlaster/issues)
- **Discussions**: [Ask questions or share ideas](https://github.com/jaycollett/OpenIRBlaster/discussions)
- **Community**: [Home Assistant Forum](https://community.home-assistant.io/)

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

Built with ❤️ for the Home Assistant community. Special thanks to:
- The ESPHome project for the amazing firmware platform
- The Home Assistant community for inspiration and support

---

**Tip**: After learning your codes, you can organize them with Tags and Notes (stored in the JSON file) for better management.

[releases-shield]: https://img.shields.io/github/release/jaycollett/OpenIRBlaster.svg
[releases]: https://github.com/jaycollett/OpenIRBlaster/releases
[license-shield]: https://img.shields.io/github/license/jaycollett/OpenIRBlaster.svg
[hacs]: https://github.com/hacs/integration
[hacsbadge]: https://img.shields.io/badge/HACS-Default-orange.svg
