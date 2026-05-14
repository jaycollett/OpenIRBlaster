# OpenIRBlaster Documentation

OpenIRBlaster is an open-source infrared transceiver designed for Home Assistant integration via ESPHome. These pages cover building, configuring, and troubleshooting the device.

For the project's elevator pitch and install instructions, see the [root README](../README.md). For a narrative build log, see the [project blog post](https://www.jaycollett.com/2026/02/openirblaster-finally-truly-simple-ir-control-for-home-assistant/).

## Hardware Specs

| Parameter | Value |
|-----------|-------|
| Microcontroller | ESP-12F (ESP8266) |
| IR Frequency | 38kHz (configurable) |
| IR LEDs | 8x IR333-A 940nm |
| Power Input | 5V DC via USB-C |
| Power Draw | ~500mA peak (1A supply recommended) |
| Connectivity | Wi-Fi 802.11 b/g/n |

## Pages

### Getting Started
- [Hardware Overview](hardware-overview.md) - Schematic walkthrough, component selection, and design rationale

### Configuration
- [Firmware & ESPHome](firmware-and-esphome.md) - Flashing instructions, YAML configuration, and integration compatibility requirements
- [Home Assistant Integration](home-assistant-integration.md) - Device setup, entities, services, and automation examples

### Reference
- [Storage Format & Manual Editing](storage-format.md) - On-disk schema for `.storage/openirblaster_*.json` and the safe procedure for hand-editing it
- [Troubleshooting](troubleshooting.md) - Common issues and solutions

### Third-Party Hardware
- [Tuya IR Blasters](third-party-devices/tuya-ir-blasters.md) - S06, S18, and similar Tuya-branded IR repeaters
- [Adding a new device guide](third-party-devices/README.md#contributing-a-new-device-guide)

## Project Resources

| Resource | Link |
|----------|------|
| Source Code | [GitHub Repository](https://github.com/jaycollett/OpenIRBlaster) |
| Hardware Files | [Eagle CAD Files](https://github.com/jaycollett/OpenIRBlaster/tree/master/hardware) |
| Blog Post | [Project Introduction](https://www.jaycollett.com/2026/02/openirblaster-finally-truly-simple-ir-control-for-home-assistant/) |
| ESPHome | [ESPHome Documentation](https://esphome.io) |

## Contributing

Contributions are welcome. Please submit issues and pull requests through the [GitHub repository](https://github.com/jaycollett/OpenIRBlaster).
