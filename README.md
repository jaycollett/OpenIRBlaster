# OpenIRBlaster

A custom Home Assistant integration for learning, storing, and replaying infrared remote control codes using ESPHome devices.

[![GitHub Release][releases-shield]][releases]
[![License][license-shield]](LICENSE)
[![hacs][hacsbadge]][hacs]

**Current release: v1.0.1**

## Introduction

New to OpenIRBlaster? Check out the [introductory blog post](https://www.jaycollett.com/2026/01/openirblaster-finally-brain-dead-simple-ir-control-for-home-assistant/) for a complete overview of the project, design decisions, and what makes it different from other IR solutions.

For detailed documentation, hardware build guides, and troubleshooting, visit the [OpenIRBlaster Wiki](https://github.com/jaycollett/OpenIRBlaster/wiki).

## What It Does

Turn any ESPHome device with an IR receiver and transmitter into a universal remote control:

- **Learn** IR codes from any remote control
- **Store** unlimited codes with custom names
- **Replay** codes with a single button press or automation
- **Control** TVs, AC units, fans, projectors, and other IR devices through Home Assistant

## Requirements

- Home Assistant 2024.1+ (Python 3.12+)
- ESPHome device with IR receiver, IR transmitter, and OpenIRBlaster firmware

For hardware details and build instructions, see the [Hardware Documentation](https://github.com/jaycollett/OpenIRBlaster/wiki/Hardware-Overview) in the Wiki.

## Installation

### HACS (Recommended)

1. Open HACS → **Integrations** → **+ Explore & Download Repositories**
2. Search for "OpenIRBlaster" and click **Download**
3. Restart Home Assistant
4. Go to **Settings** → **Devices & Services** → **Add Integration** → search "OpenIRBlaster"

### Manual Installation

1. Download the [latest release](https://github.com/jaycollett/OpenIRBlaster/releases)
2. Copy `custom_components/openirblaster` to your Home Assistant `custom_components` directory
3. Restart Home Assistant and add the integration via Settings

## Quick Start

1. **Add the integration** - Select your ESPHome OpenIRBlaster device from the dropdown
2. **Learn a code** - Enter a name in the "Code Name" field, press "Learn IR Code", then press a button on your remote within 30 seconds
3. **Use it** - A new button entity appears that you can press or use in automations

```yaml
# Example automation
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

For advanced usage, services reference, and troubleshooting, see the [Wiki](https://github.com/jaycollett/OpenIRBlaster/wiki).

## Development

Contributions are welcome! See [`CLAUDE.md`](CLAUDE.md) for development guidelines and [`TESTING.md`](TESTING.md) for testing instructions.

```bash
git clone https://github.com/jaycollett/OpenIRBlaster.git
cd OpenIRBlaster
python3 -m venv venv && source venv/bin/activate
pip install -r requirements_dev.txt
pytest
```

## Support

- [Report bugs or request features](https://github.com/jaycollett/OpenIRBlaster/issues)
- [Project Wiki](https://github.com/jaycollett/OpenIRBlaster/wiki)

## License

MIT License - see [LICENSE](LICENSE) for details.

---

[releases-shield]: https://img.shields.io/github/release/jaycollett/OpenIRBlaster.svg
[releases]: https://github.com/jaycollett/OpenIRBlaster/releases
[license-shield]: https://img.shields.io/github/license/jaycollett/OpenIRBlaster.svg
[hacs]: https://github.com/hacs/integration
[hacsbadge]: https://img.shields.io/badge/HACS-Default-orange.svg
