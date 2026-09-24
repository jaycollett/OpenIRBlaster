# OpenIRBlaster

An open-source IR receiver and transmitter for Home Assistant. Custom PCB, 3D-printed case, ESPHome firmware, about $22 to $25 in parts.

[![GitHub Release][releases-shield]][releases]
[![License][license-shield]](LICENSE)
[![hacs][hacsbadge]][hacs]

📖 **[Read the full story and build guide on my blog](https://www.jaycollett.com/2026/02/openirblaster-finally-truly-simple-ir-control-for-home-assistant/)**

## The integration is deprecated. The hardware is not.

Home Assistant 2026.4 added a built-in `infrared` entity platform, and [HAIR](https://github.com/DAB-LABS/HAIR) builds a full IR code manager on top of it: a live signal sniffer, protocol decoding, climate state matrices, and import from SmartIR, Flipper Zero, LIRC and Girr. It does everything this integration does and a great deal more, and it is in the HACS default store.

So this integration is winding down. It still works, it is not going to break tomorrow, and nothing is being deleted in this release. It will not gain new features.

The hardware is unaffected and is where this project continues. OpenIRBlaster is a board, a case, a bill of materials and a firmware image, none of which HAIR provides.

**If you are already using this integration:** move your codes across before you delete its storage file. From version 1.3.2, removing the integration leaves that file in place. Version 1.3.1 and earlier deleted it along with the integration, so on those versions update or move your codes first. Your stored codes hold the carrier frequency measured when each was learned, and the new infrared platform does not report one, so anything re-learned later comes back at the 38 kHz default. See [Moving your codes to HAIR](#moving-your-codes-to-hair). Nothing is deleted and your setup keeps working while you check the result.

**If you are new here:** build the hardware, flash it, and use it with HAIR.

## What it is

A dedicated ESP8266 board built around IR, rather than a general-purpose dev board with an LED soldered on.

Transistor-driven IR LEDs (eight of them, 39 ohm limiting resistors, IRLML6344 MOSFET) give strong output and 360 degree coverage, so it works across a room rather than only when pointed at the target. A TSOP38238 receiver handles learning. The ESPHome firmware ships with `dashboard_import`, so the ESPHome dashboard can adopt the device with one click.

Everything needed to build one is in [`hardware/`](hardware/): schematic and board layout, the bill of materials, STLs for the case, the firmware source and a prebuilt binary.

## Requirements

- Home Assistant 2024.12 or newer for this integration.
- For HAIR, check its own requirements. Native IR capture and plucking need Home Assistant 2026.6 or newer, because that is the release where the infrared receiver API landed. 2026.9 or newer is the safer floor.
- An OpenIRBlaster board, or other ESPHome hardware with an IR receiver and transmitter.

See the [Hardware Overview](docs/hardware-overview.md) for the build.

## Moving your codes to HAIR

### Do this before you delete anything

Every code you learned here carries the carrier frequency measured when it was captured. Home Assistant's infrared platform does not report a carrier, so a code you learn again afterwards comes back at the 38 kHz default.

Most remotes are 38 kHz and would not notice. A device running at 36 or 40 kHz would, and for those the difference is the code working or not working. That measured value exists in one place only, this integration's storage file, and re-learning cannot bring it back.

Both routes below preserve it. Take one of them before you delete `.storage/openirblaster_<entry_id>`.

From version 1.3.2, removing the integration in Home Assistant keeps that file, so your codes are still on disk afterwards and the command-line export below can convert them. Version 1.3.1 and earlier deleted the file when you deleted the integration entry, so if you are on one of those versions, update or export first.

If you remove a blaster and add it again, Home Assistant gives it a new entry ID and a new, empty storage file. The old file stays next to it with your codes in it. Once those codes are safely in HAIR you can delete the old file by hand.

### Pluck from HAIR (recommended)

HAIR pulls the codes out of this integration directly. No files to move, no remote to point at anything, and no infrared is broadcast while it happens.

1. Install HAIR from HACS and set it up.
2. Open HAIR, go to the **Plucker** tab, and add OpenIRBlaster as a blaster.
3. Pluck your codes by name.

This works because the integration implements HAIR's pluckable contract. See [Plucking codes into HAIR](docs/pluckable.md) for what that means and how it works.

### Export to a file

If you would rather move files yourself, or HAIR is not installed yet.

From the UI, while this integration is still installed:

1. Go to **Developer Tools** -> **Actions**.
2. Choose **OpenIRBlaster: Export codes to HAIR**.
3. Pick your device, and optionally choose how to split the codes into files.
4. Run it.

Files land in `hair/wigs/` in your Home Assistant config directory, which is where HAIR looks.

HAIR treats one file as one remote, so the **Split into** option matters if your library covers several devices. Splitting by tag or by the first word of each code name gives you one remote per device instead of one long list. You can re-split inside HAIR later either way.

From the command line, which also works after you have removed the integration (on 1.3.2 or later, where removal keeps the file):

```bash
python3 tools/openirblaster_to_wig.py ~/.homeassistant/.storage/openirblaster_<entry_id>
```

The file name has no extension, and there is one per blaster, so `ls ~/.homeassistant/.storage/openirblaster_*` shows you what to pass.

Run `--help` for output directory and grouping options. It needs nothing but Python 3.12 or newer and never writes to the file it reads. `custom_components/openirblaster/wig_export.py` is the whole implementation in one file with no imports from anything else, so you can copy that single file somewhere and run it if the repository is not handy.

### After moving

Check the codes work in HAIR before removing anything here. If a code did not convert, or carried tags or notes, the file export writes `openirblaster-export-receipt.txt` next to the wigs listing what was dropped and why. Tags and notes have no equivalent in HAIR's format, so they are reported rather than silently merged.

Keep your `.storage` file until you are satisfied. Removing the integration does not touch it, so when you no longer need it, delete it by hand.

## Installation

### HACS

1. Open HACS.
2. Click **Integrations**.
3. Click **+ Explore & Download Repositories**.
4. Search for "OpenIRBlaster".
5. Click **Download**.
6. Restart Home Assistant.
7. Go to **Settings** → **Devices & Services** → **Add Integration** and search for "OpenIRBlaster".

### Manual

1. Download the [latest release](https://github.com/jaycollett/OpenIRBlaster/releases).
2. Copy `custom_components/openirblaster` into your Home Assistant `custom_components` directory.
3. Restart Home Assistant.
4. Add the integration from **Settings** → **Devices & Services**.

## Using the integration

### Learn a code

1. Find the **Code Name** text field in your device's entity list.
2. Enter a name, for example "TV Power".
3. Press **Learn IR Code**.
4. Within 30 seconds, point your remote at the receiver and press the button.
5. A new button entity appears with that name.

### Manage codes

Rename by calling `openirblaster.rename_code` with the code's `id` and a `new_name`. The button updates immediately and its entity ID does not change, so automations keep working.

Delete from **Settings** → **Devices & Services** → **OpenIRBlaster** → **Configure** → **Manage IR Codes**. Deletion is always select-then-confirm.

Codes can also be saved, sent, renamed and deleted from scripts. See the [Home Assistant Integration](docs/home-assistant-integration.md) docs for the full service reference.

### Use in automations

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

## Compatibility

The integration finds devices by ESPHome project name, looking for firmware that declares `project.name: "jaycollett.openirblaster"`. If you are building your own hardware, include that identifier in your ESPHome YAML or fork the integration.

### Third-party devices

Community members have run OpenIRBlaster on hardware it was not designed for. See [`docs/third-party-devices/`](docs/third-party-devices/):

- [Tuya IR Blasters](docs/third-party-devices/tuya-ir-blasters.md), covering S06, S18 and similar Tuya-branded repeaters

[PRs adding a guide are welcome](docs/third-party-devices/README.md#contributing-a-new-device-guide).

## Documentation

Full documentation lives in [`docs/`](docs/README.md):

- [Hardware Overview](docs/hardware-overview.md), schematic, components and build guide
- [Firmware & ESPHome](docs/firmware-and-esphome.md), flashing and configuration
- [Home Assistant Integration](docs/home-assistant-integration.md), setup, entities, services and automation examples
- [Plucking codes into HAIR](docs/pluckable.md), how HAIR pulls codes out of this integration
- [Storage Format & Manual Editing](docs/storage-format.md), on-disk schema and hand-edit procedure
- [Troubleshooting](docs/troubleshooting.md), common issues and solutions

## Development

- [`TESTING.md`](TESTING.md), testing instructions
- [`hardware/`](hardware/), hardware design files

### ESPHome firmware

The firmware configuration is at [`hardware/firmware/factory_flash.yaml`](hardware/firmware/factory_flash.yaml). To contribute changes, modify the YAML, test on your own device, and keep event names, service calls and entity IDs compatible with the integration. See the [Firmware & ESPHome](docs/firmware-and-esphome.md) docs.

### Integration

```bash
git clone https://github.com/jaycollett/OpenIRBlaster.git
cd OpenIRBlaster
python3 -m venv venv
source venv/bin/activate
pip install -r requirements_dev.txt

pytest
```

## Support

- [Report bugs or request features](https://github.com/jaycollett/OpenIRBlaster/issues)
- [Project documentation](docs/README.md)

## License

MIT. See [LICENSE](LICENSE).

## Acknowledgments

Built for the Home Assistant community. Thanks to the ESPHome project for the firmware platform, to the Home Assistant community, and to [DAB-LABS](https://github.com/DAB-LABS/HAIR) for building the IR code manager this project no longer needs to.

### Transparency note: AI-assisted development

The Home Assistant integration for this project was developed with assistance from [Claude Code](https://claude.ai/code), Anthropic's AI coding assistant. AI-assisted development is a powerful tool when used responsibly by engineers who understand the code being generated, validate its correctness, and take ownership of the final result. I reviewed, tested, and take full responsibility for all code in this repository. AI assistance accelerated development but doesn't replace engineering judgment, thorough testing, or understanding of the underlying systems.

---

[releases-shield]: https://img.shields.io/github/v/release/jaycollett/OpenIRBlaster
[releases]: https://github.com/jaycollett/OpenIRBlaster/releases
[license-shield]: https://img.shields.io/github/license/jaycollett/OpenIRBlaster.svg
[hacs]: https://github.com/hacs/integration
[hacsbadge]: https://img.shields.io/badge/HACS-Default-orange.svg
