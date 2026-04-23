# Third-Party Device Support

OpenIRBlaster was designed around a [purpose-built PCB](../../hardware/), but the firmware and Home Assistant integration are not strictly tied to that hardware. Any ESPHome-flashable IR device that exposes the same events and services can work with the integration.

This directory collects community-contributed guides for running OpenIRBlaster on hardware that wasn't designed for it. These are provided as-is by the contributors listed in each guide; they may not have been tested by the maintainer.

## Available Guides

| Device Family | Notes | Contributor |
|---|---|---|
| [Tuya IR Blasters](tuya-ir-blasters.md) | Various Tuya-branded IR repeaters (S06, S18, etc.) flashed via tuya-cloudcutter | [@Stoatwblr](https://github.com/Stoatwblr) |

## What You'll Need to Make It Work

The Home Assistant integration identifies compatible devices by ESPHome project name. Any ESPHome YAML used with this integration must declare:

```yaml
esphome:
  project:
    name: "jaycollett.openirblaster"
    version: "1.0.0"
```

It also needs to expose the events and services the integration listens for. Use [`hardware/firmware/factory_flash.yaml`](../../hardware/firmware/factory_flash.yaml) as the reference implementation - the event names, service signatures, and entity IDs there define the contract.

## Contributing a New Device Guide

If you've successfully run OpenIRBlaster on hardware not listed here, PRs are welcome. A useful guide includes:

- Device name(s) and where to buy them
- The chip / board variant(s) you tested on
- Pinout(s) for IR TX, IR RX, status LED, and any buttons
- The flashing method (tuya-cloudcutter, esptool, etc.)
- A working ESPHome YAML snippet (or full file) showing the device-specific bits
- Anything that surprised you (case opening difficulty, GPIO probing, etc.)

Open a PR adding a new file to this directory and a row to the table above.
