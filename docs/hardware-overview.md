# Hardware Overview

This page covers the hardware components and assembly for the OpenIRBlaster.

## Recommended Components

| Component | Specification | Notes |
|-----------|--------------|-------|
| Microcontroller | ESP8266 (ESP-12E/ESP-12F) or ESP32 | ESP-12F recommended |
| IR Receiver | TSOP38238 | Connected to GPIO5 |
| IR LED | 950nm IR LED (IR333-A or similar) | Connected to GPIO14 |
| MOSFET | IRLML6344 or similar logic-level | For driving IR LED(s) |
| Power | 5V DC via USB-C | 1A supply recommended |

## Circuit Design

The OpenIRBlaster uses a simple but effective design:

- **IR Receiver**: The TSOP38238 connects directly to GPIO5 with built-in signal conditioning
- **IR Transmitter**: GPIO14 drives an IRLML6344 MOSFET which switches the IR LED array
- **Power**: 5V USB-C input with AZ1117-3.3 voltage regulator for the ESP8266

### Schematic

![OpenIRBlaster Schematic](https://github.com/jaycollett/OpenIRBlaster/blob/master/hardware/Eagle%20Files/open_ir_blaster_sch.png?raw=true)

Full Eagle CAD files are available in the [hardware/Eagle Files](https://github.com/jaycollett/OpenIRBlaster/tree/master/hardware/Eagle%20Files) directory.

## GPIO Assignments

| GPIO | Function |
|------|----------|
| GPIO5 | IR Receiver (TSOP38238) |
| GPIO14 | IR Transmitter (via MOSFET) |

## Build Options

### Option 1: Custom PCB

Order PCBs using the Eagle files in the repository. The board is designed for easy hand soldering with 0805 SMD components.

### Option 2: Breadboard Prototype

For testing, you can wire up the components on a breadboard:
1. Connect TSOP38238 to GPIO5
2. Connect IR LED through MOSFET to GPIO14
3. Add appropriate current limiting resistor for IR LED

For a full narrative build walkthrough, see the [project blog post](https://www.jaycollett.com/2026/02/openirblaster-finally-truly-simple-ir-control-for-home-assistant/).

## Design Files

- [Eagle Schematic (.sch)](https://github.com/jaycollett/OpenIRBlaster/tree/master/hardware/Eagle%20Files)
- [Eagle Board (.brd)](https://github.com/jaycollett/OpenIRBlaster/tree/master/hardware/Eagle%20Files)

---

*See [Troubleshooting](troubleshooting.md) for hardware debugging tips.*
