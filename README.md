# OpenIRBlaster Integration for Home Assistant

A custom Home Assistant integration for managing infrared remote codes with ESPHome-based IR blaster devices.

[![GitHub Release][releases-shield]][releases]
[![License][license-shield]](LICENSE)
[![hacs][hacsbadge]][hacs]

## Overview

OpenIRBlaster is a Home Assistant custom integration that provides a complete solution for learning, storing, and transmitting infrared remote control codes using ESPHome devices. It offers an intuitive interface for capturing IR signals from your existing remotes and replaying them to control your devices.

## Features

- **Learn IR Codes**: Capture infrared signals from any remote control
- **Store Unlimited Codes**: Save learned codes with custom names, tags, and notes
- **One-Click Transmission**: Send stored IR codes with a single button press
- **Multi-Device Support**: Manage multiple IR blaster devices simultaneously
- **Real-Time Status**: Monitor learning session state and last learned code details
- **Service Integration**: Full Home Assistant service support for automation
- **Collision-Safe Storage**: Automatic handling of duplicate code names
- **ESPHome Native**: Seamless integration with ESPHome firmware

## Requirements

- Home Assistant 2024.1 or newer (Python 3.12+)
- ESPHome device with IR receiver and transmitter
- OpenIRBlaster ESPHome firmware (see `example_firmware.yaml`)

## Installation

### HACS (Recommended)

_Coming soon_

### Manual Installation

1. Download the latest release from GitHub
2. Extract the `openirblaster` folder to your `custom_components` directory
3. Restart Home Assistant

## Configuration

### Adding the Integration

1. Go to **Settings** → **Devices & Services**
2. Click **Add Integration**
3. Search for "OpenIRBlaster"
4. Enter your ESPHome device name (e.g., `openirblaster-64c999`)
5. Enter a unique device ID (or use the default)
6. Verify the learning mode switch entity ID
7. Click **Submit**

### ESPHome Configuration

Your ESPHome device must have the OpenIRBlaster firmware installed. The integration expects:

- An IR receiver for learning codes
- An IR transmitter for sending codes
- A learning mode switch entity
- Event publishing when codes are learned

See `example_firmware.yaml` for a complete ESPHome configuration example.

## Usage

### Learning IR Codes

1. Press the **Learn IR Code** button entity
2. Point your remote at the IR receiver
3. Press the button on your remote
4. The integration captures the IR signal
5. Open the integration's options to save the code with a name

### Sending IR Codes

Once codes are saved, you'll see button entities for each code:

- Press the button to transmit the IR code
- Use in automations and scripts
- Call via services for advanced control

### Entities Created

For each OpenIRBlaster device, the integration creates:

**Buttons:**
- `button.{device}_learn_ir_code` - Start learning mode
- `button.{device}_send_last_learned` - Send the most recently learned code
- `button.{device}_{code_name}` - One button per saved code

**Sensors:**
- `sensor.{device}_last_learned_code_name` - Name/ID of last learned code
- `sensor.{device}_last_learned_timestamp` - When the code was learned
- `sensor.{device}_last_learned_pulse_count` - Number of pulses in the code

## Services

### `openirblaster.learn_start`

Start a learning session.

```yaml
service: openirblaster.learn_start
data:
  config_entry_id: "01KESZQ4GF6WSK5XBAA19N96MM"
  timeout: 30
```

### `openirblaster.send_code`

Send a stored IR code.

```yaml
service: openirblaster.send_code
data:
  config_entry_id: "01KESZQ4GF6WSK5XBAA19N96MM"
  code_id: "tv_power"
```

You can also override the stored code parameters:

```yaml
service: openirblaster.send_code
data:
  config_entry_id: "01KESZQ4GF6WSK5XBAA19N96MM"
  code_id: "custom_code"
  carrier_hz: 38000
  pulses: [9000, 4500, 560, 560, ...]
```

### `openirblaster.delete_code`

Delete a stored code.

```yaml
service: openirblaster.delete_code
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
  new_name: "TV Power Toggle"
```

## Automation Examples

### Learn and Save Code on Schedule

```yaml
automation:
  - alias: "Learn IR Code Every Morning"
    trigger:
      - platform: time
        at: "08:00:00"
    action:
      - service: openirblaster.learn_start
        data:
          config_entry_id: "01KESZQ4GF6WSK5XBAA19N96MM"
          timeout: 60
```

### Send Code Based on Condition

```yaml
automation:
  - alias: "Turn off TV at Night"
    trigger:
      - platform: time
        at: "23:00:00"
    action:
      - service: button.press
        target:
          entity_id: button.openirblaster_64c999_tv_power
```

## Storage

Learned codes are stored in `.storage/openirblaster_{entry_id}.json` within your Home Assistant configuration directory. Each code includes:

- Unique ID (slugified name)
- Display name
- Carrier frequency (Hz)
- Pulse array (microseconds)
- Tags (for organization)
- Notes (for documentation)
- Creation timestamp

## Troubleshooting

### Integration Won't Add

- Verify your ESPHome device is online and accessible
- Check that the learning mode switch entity exists
- Ensure the entity ID follows the format: `switch.{device}_ir_learning_mode`

### Learning Times Out

- Increase the timeout parameter (default: 30 seconds)
- Verify the IR receiver is working in ESPHome logs
- Ensure the remote is pointed directly at the receiver
- Check that learning mode is actually enabled

### Codes Don't Transmit

- Verify the ESPHome transmitter is configured correctly
- Check Home Assistant logs for transmission errors
- Ensure the carrier frequency matches your device
- Test with the "Send Last Learned" button first

## Development

### Setting Up Development Environment

```bash
# Clone the repository
git clone https://github.com/jaycollett/OpenIRBlasterIntegration.git
cd OpenIRBlasterIntegration

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements_dev.txt

# Run tests
pytest
```

### Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=custom_components/openirblaster

# Run specific test file
pytest tests/test_learning.py
```

### Code Quality

```bash
# Format code
black custom_components/openirblaster

# Lint code
pylint custom_components/openirblaster

# Type checking
mypy custom_components/openirblaster
```

## Architecture

The integration follows Home Assistant best practices:

- **Config Flow**: User-friendly setup via UI
- **Options Flow**: Save learned codes with metadata
- **Platform Architecture**: Separate button and sensor platforms
- **Storage Management**: JSON-based persistent storage with migration support
- **State Machine**: Robust learning session management with timeout handling
- **Event-Driven**: Listens for ESPHome events to capture learned codes
- **Callback Management**: Proper registration and cleanup to prevent memory leaks

Key components:

- `__init__.py` - Integration setup and lifecycle management
- `config_flow.py` - Configuration and options flows
- `button.py` - Button entities for learning and transmission
- `sensor.py` - Status sensors for monitoring
- `learning.py` - Learning session state machine
- `storage.py` - Persistent code storage with collision handling
- `services.py` - Home Assistant service definitions

See [CLAUDE.md](CLAUDE.md) for detailed development guidance and [openirblaster_ha_integration_spec.md](openirblaster_ha_integration_spec.md) for the technical specification.

## Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Make your changes with tests
4. Ensure all tests pass
5. Submit a pull request

Please follow the existing code style and include tests for new features.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- Built for the Home Assistant community
- Integrates with ESPHome firmware
- Inspired by various IR remote control integrations

## Support

- **Issues**: [GitHub Issues](https://github.com/jaycollett/OpenIRBlasterIntegration/issues)
- **Discussions**: [GitHub Discussions](https://github.com/jaycollett/OpenIRBlasterIntegration/discussions)
- **Home Assistant Community**: [Community Forum](https://community.home-assistant.io/)

---

Made with ❤️ for Home Assistant

[releases-shield]: https://img.shields.io/github/release/jaycollett/OpenIRBlasterIntegration.svg
[releases]: https://github.com/jaycollett/OpenIRBlasterIntegration/releases
[license-shield]: https://img.shields.io/github/license/jaycollett/OpenIRBlasterIntegration.svg
[hacs]: https://github.com/hacs/integration
[hacsbadge]: https://img.shields.io/badge/HACS-Default-orange.svg
