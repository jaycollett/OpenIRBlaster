# OpenIRBlaster for Home Assistant

A Home Assistant custom integration that lets you learn, store, and replay infrared remote control codes using ESPHome devices.

[![GitHub Release][releases-shield]][releases]
[![License][license-shield]](LICENSE)
[![hacs][hacsbadge]][hacs]

Current release: **v1.0.1**

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

For hardware build instructions, see the [Hardware Overview](https://github.com/jaycollett/OpenIRBlaster/wiki/Hardware-Overview) in the wiki.

## Installation

### HACS (Recommended)

1. Open HACS in your Home Assistant instance
2. Click on **Integrations**
3. Click the **+ Explore & Download Repositories** button
4. Search for "OpenIRBlaster"
5. Click **Download**
6. Restart Home Assistant
7. Go to **Settings** → **Devices & Services** → **Add Integration** → search "OpenIRBlaster"

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
4. Select your ESPHome OpenIRBlaster device from the dropdown (devices must already be connected via ESPHome)
5. Click **Submit**

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
          entity_id: button.openirblaster_tv_power
```

For detailed documentation on entities, services, and advanced usage, see the [Home Assistant Integration](https://github.com/jaycollett/OpenIRBlaster/wiki/Home-Assistant-Integration) wiki page.

## Documentation

- [Hardware Overview](https://github.com/jaycollett/OpenIRBlaster/wiki/Hardware-Overview) — Schematic, components, and build options
- [Firmware & ESPHome](https://github.com/jaycollett/OpenIRBlaster/wiki/Firmware-and-ESPHome) — Flashing and configuration
- [Home Assistant Integration](https://github.com/jaycollett/OpenIRBlaster/wiki/Home-Assistant-Integration) — Setup, entities, services, and automation examples
- [Troubleshooting](https://github.com/jaycollett/OpenIRBlaster/wiki/Troubleshooting) — Common issues and solutions

## Development

Want to contribute? Check out:

- [`TESTING.md`](TESTING.md) - Testing instructions
- [`hardware/`](hardware/) - Hardware design files and documentation

### ESPHome Firmware

The ESPHome firmware configuration is located at [`hardware/firmware/factory_flash.yaml`](hardware/firmware/factory_flash.yaml). To contribute firmware changes:

1. Modify the YAML configuration as needed
2. Test with your own ESPHome device before submitting a PR
3. Ensure compatibility with the Home Assistant integration (event names, service calls, entity IDs)

See the [Firmware & ESPHome](https://github.com/jaycollett/OpenIRBlaster/wiki/Firmware-and-ESPHome) wiki page for configuration details.

### Home Assistant Integration

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

## Support

- [Report bugs or request features](https://github.com/jaycollett/OpenIRBlaster/issues)
- [Project Wiki](https://github.com/jaycollett/OpenIRBlaster/wiki)

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

Built for the Home Assistant community. Special thanks to:
- The ESPHome project for the amazing firmware platform
- The Home Assistant community for inspiration and support

### Transparency Note: AI-Assisted Development

The Home Assistant integration for this project was developed with assistance from [Claude Code](https://claude.ai/code), Anthropic's AI coding assistant. AI-assisted development is a powerful tool when used responsibly by engineers who understand the code being generated, validate its correctness, and take ownership of the final result. I reviewed, tested, and take full responsibility for all code in this repository. AI assistance accelerated development but doesn't replace engineering judgment, thorough testing, or understanding of the underlying systems.

---

[releases-shield]: https://img.shields.io/github/release/jaycollett/OpenIRBlaster.svg
[releases]: https://github.com/jaycollett/OpenIRBlaster/releases
[license-shield]: https://img.shields.io/github/license/jaycollett/OpenIRBlaster.svg
[hacs]: https://github.com/hacs/integration
[hacsbadge]: https://img.shields.io/badge/HACS-Default-orange.svg
