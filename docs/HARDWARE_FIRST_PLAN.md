# OpenIRBlaster hardware-first plan

Status: proposal, awaiting approval. No source files changed.
Written 2026-09-19 against v1.2.3 (commit 6e8f4ad, branch master, clean).

The premise: HAIR (https://github.com/DAB-LABS/HAIR, MIT) already did the infrared-domain migration this project was about to start, at a scope OpenIRBlaster was never going to match. HAIR owns no hardware and no firmware. OpenIRBlaster does. This plan moves the repo's centre of gravity to the hardware, makes OpenIRBlaster a first-class device under HAIR, and gets existing users' code libraries across without re-learning anything.

Sources. Repo claims carry a path or `file:line`. HAIR claims were read from the clone at `scratchpad/HAIR` and are cited `HAIR:<path>:<line>`; they agree with the independent analysis at `scratchpad/hair-analysis.md`, and where I measured something that document states more strongly than I can, I say so. ESPHome claims were read from `raw.githubusercontent.com/esphome/esphome/dev`. `infrared_protocols` claims were executed against version 10.1.0 under Python 3.14.7.

---

## Priority zero: the chip, and what each answer costs

### The hardware is ESP8266, ESP-12F module, ESPHome board `esp12e`

Settled from the repo, four independent confirmations:

- `hardware/BOM.csv:12`: `MCU,ESP8266,MCU,ESP-12F,ESP-12F`
- `hardware/firmware/factory_flash.yaml:21-22`: `esp8266:` then `board: esp12e`
- `hardware/firmware/factory_flash.yaml:195`: "Hardware schematic shows GPIO4/GPIO5 are swapped in the ESP-12F footprint"
- `custom_components/openirblaster/__init__.py:394`: `model="ESP8266 IR Blaster"`

There is no ESP32 variant anywhere in the repo. Every shipped unit is this board.

### Can ir_rf_proxy run on it

I cannot settle this from the repo and ESPHome source alone, and I will not guess. Here is exactly what the evidence does and does not establish.

Verified, and it is the encouraging half. Nothing gates ESP8266 at config time. I grepped `esphome/components/ir_rf_proxy/infrared.py`, `esphome/components/ir_rf_proxy/__init__.py` and `esphome/components/infrared/__init__.py` for `esp8266`, `esp32`, `only_on`, `not_on` and `PLATFORM`, and the only hit is `IS_PLATFORM_COMPONENT = True` (`infrared/__init__.py:22`). The C++ carries feature guards, `#ifdef USE_IR_RF` and `#ifdef USE_RADIO_FREQUENCY` (`ir_rf_proxy/ir_rf_proxy.h:9,13,19,45`), and no platform guards. The component is a thin layer over `remote_base` (`AUTO_LOAD = ["remote_base"]`, `infrared/__init__.py:20`), attaching by id through `remote_base.attach_receiver` (`ir_rf_proxy/infrared.py:89-90`). `remote_base` works on ESP8266 today, which is how the current firmware functions at all. So there is no structural reason it should fail.

Not verified, and it cannot be from source. Whether it compiles for `esp12e`, whether the image fits in flash, and whether it runs without exhausting RAM once the native API also holds an infrared receive subscription. The existing firmware is already managing RAM deliberately: `buffer_size: 6kb` and a comment at `factory_flash.yaml:204` reading "ESP8266-safe: avoid dump: all (can contribute to RAM pressure)". That is not a board with headroom.

The discouraging half, and it deserves weight. Nobody upstream has an ESP8266 config.

- All five HAIR reference configs are ESP32 family: `esp32dev`, `esp32-c3-devkitm-1`, `esp32doit-devkit-v1`, `esp32-s3-devkitc-1`, `seeed_xiao_esp32c3` (`HAIR:esphome/README.md`, availability table).
- The official `esphome/infrared-proxies` repo contains exactly one device directory, `xiao-ir-mate`, ESP32-C3. I listed the repo through the GitHub API.
- ESPHome's own `ir_rf_proxy` docs publish no chip support matrix, which the parallel analysis also found (`hair-analysis.md:94`).

Zero ESP8266 prior art across all three. That is not proof of failure. It does mean OpenIRBlaster would be first, with nobody to copy and nobody to ask.

### What would settle it

One command, which the parallel agent is running:

```
esphome compile factory_flash.yaml    # with the infrared: block from section 2, ESPHome 2026.5.0+
```

Three outcomes worth distinguishing, because they are not the same problem:

1. Compiles and fits, runs stable. Proceed with the whole plan.
2. Compiles but overruns flash or RAM. Recoverable by trimming the firmware: drop `dump:`, drop the legacy `send_ir_raw` and `replay_last_ir` services and the `openirblaster_learned` event once HAIR is the path, shrink `buffer_size`. That reclaims real space, since those exist only to serve the integration this plan winds down.
3. Does not compile for `esp8266`. Not recoverable in firmware.

### Consequences of each answer

If it works, existing units follow with a reflash and no board revision. Everything below proceeds as written.

If it does not, there is no fallback. HAIR talks only to the infrared domain ("HAIR does not talk to hardware directly. It sits on HA's native infrared platform for both capture and send", and `dependencies: ["http", "infrared"]` in `HAIR:custom_components/hair/manifest.json`). A device that cannot register an `infrared` entity is invisible to HAIR, whatever else its firmware exposes. The legacy event and service path does not help, because HAIR will not read it.

That leaves two branches, and both are Jay's call rather than mine:

- Revise the board to ESP32-C3. A schematic change, a new BOM, a new layout, a fab run and new firmware. Weeks and real money. It also gets the chip everyone else in this ecosystem is on, which has value beyond this one problem.
- Accept that Rev A stays on the legacy integration and only a future revision works with HAIR. Cheap now, and it means the wind-down in section 4 cannot go past a thin shim, because the shim is the only way Rev A users keep working at all.

Note what does not change under either branch. The export tool in section 3 reads a JSON file and writes a JSON file. It never touches the device. Existing users get their code libraries out regardless of how the compile goes, and that is why it is the first thing to build.

---

## 1. Hardware asset inventory

Eight files, 1.2 MB, all under `hardware/`.

| Asset | Path | Size | Notes |
|---|---|---|---|
| Schematic | `hardware/Eagle Files/Open_IR_Blaster.sch` | 607 KB | Autodesk Eagle format |
| Board layout | `hardware/Eagle Files/Open_IR_Blaster.brd` | 111 KB | Autodesk Eagle format |
| Schematic image | `hardware/Eagle Files/open_ir_blaster_sch.png` | 100 KB | Rendered, viewable without Eagle |
| Bill of materials | `hardware/BOM.csv` | 693 B | 14 line items |
| Enclosure top | `hardware/3DPrinterFiles/Top.stl` | 206 KB | STL only |
| Enclosure bottom | `hardware/3DPrinterFiles/Bottom.stl` | 347 KB | STL only |
| Factory firmware source | `hardware/firmware/factory_flash.yaml` | 9.3 KB | ESPHome YAML, project version `0.5.0` at line 14 |
| Factory firmware binary | `hardware/firmware/factory_flash.bin` | 420 KB | Prebuilt, flashable via ESPHome Web |

### What does not exist

Checked rather than assumed, because the brief asked for several of these by name:

- No gerbers. I searched the repo for `*.gbr`, `*.gbl`, `*.gtl`, `*.drl` and `*.zip` and found none. The Eagle `.brd` can generate them, but no fab-ready output is committed, so nobody can order a board from this repo without installing Eagle and running a CAM job.
- No drill files, pick-and-place, fab notes or assembly drawing.
- No KiCad project. Eagle only, which matters because Eagle is end-of-life as a standalone product and KiCad is where the open-hardware audience now is.
- No STEP, 3MF or source CAD for the case. Two STLs, so it cannot be modified without remodelling it.
- No hardware-scoped licence. The repo `LICENSE` covers the software; board and case normally carry a separate CERN-OHL or CC-BY-SA.

For a repo whose argument is about to become "we own the hardware", the missing fab package is the most visible gap.

### Circuit summary

| Function | Part | GPIO | Config |
|---|---|---|---|
| IR receive | TSOP38238, 38 kHz (`BOM.csv:14`) | GPIO5 | `INPUT_PULLUP`, inverted (`factory_flash.yaml:197-202`) |
| IR transmit | IR333-A 940 nm (`BOM.csv:13`) via IRLML6344 MOSFET (`BOM.csv:10`) | GPIO14 | `carrier_duty_percent: 50%` (`factory_flash.yaml:283-285`) |
| LED current limiting | 8 x 39 ohm R1210 (`BOM.csv:6`) | | Eight in parallel, a hard-driven emitter |
| Power | Adafruit 4907 USB port (`BOM.csv:8`), AZ1117IH-3.3 (`BOM.csv:9`) | | |

Receiver tuning today: `buffer_size: 6kb`, `tolerance: 50%`, `filter: 50us`, `idle: 25ms`, `dump: raw` (`factory_flash.yaml:204-213`).

The firmware ships `dashboard_import` (`factory_flash.yaml:17-19`) pointing at `github://jaycollett/OpenIRBlaster/hardware/firmware/factory_flash.yaml@master`, so the device is adoptable straight from the ESPHome dashboard. That is a real distribution asset and it should survive every change below.

---

## 2. ESPHome ir_rf_proxy configuration

Conditional on priority zero. Do not ship this until the compile passes.

### 2.1 How the component works, and why the legacy path survives

`ir_rf_proxy` is a platform of ESPHome's `infrared:` component. Its schema requires exactly one of `remote_transmitter_id` or `remote_receiver_id`, each a `cv.use_id` reference to an existing component (`ir_rf_proxy/infrared.py:24-38`). It sits on top of `remote_receiver` and `remote_transmitter` rather than replacing them, so a device doing both needs two entries against the same hardware.

That is what makes the transition cheap and reversible. Adding an `infrared:` block is purely additive. The existing `send_ir_raw` service (`factory_flash.yaml:30-43`), the `esphome.openirblaster_learned` event (`:64-77`, `:261-266`) and the `replay_last_ir` recovery service keep working against the same `ir_rx` and `ir_tx` ids. One firmware serves both the legacy integration and HAIR, so users migrate on their own schedule instead of on a flag day, and a bad ESPHome release does not strand anybody. Keep both blocks.

Two config rules, read from source:

- A transmitter whose `carrier_duty_percent` is 0 or 100 is rejected at final validation (`ir_rf_proxy/infrared.py:63-69`). OpenIRBlaster already sets 50% (`factory_flash.yaml:285`), so this passes unchanged.
- `receiver_frequency` is rejected on a transmitter entry (`ir_rf_proxy/infrared.py:44-48`), and on a receiver entry the source calls it "metadata only, no hardware effect" (`:92-94`). It never reaches Home Assistant, which is why captured signals arrive with `modulation=None`.

Require ESPHome 2026.5.0 or newer, not the bare 2026.1.0 minimum. The component broke HA entity setup as late as 2026-02-24, gained `receiver_frequency` in March and an `on_control` trigger in May. It is also marked EXPERIMENTAL in its own source, verbatim: "This component is EXPERIMENTAL. The API (both Python configuration and C++ interfaces) may change at any time without following the normal breaking changes policy." (`infrared/__init__.py:4-8`).

### 2.2 Proposed config

Written to HAIR's contribution convention. Their header template (`HAIR:esphome/_template/header-template.yaml`) is mandatory, and their README states PRs without a fully filled header are not merged.

```yaml
# ============================================================================
# HAIR ESPHome Config
# ----------------------------------------------------------------------------
# Device:            OpenIRBlaster (ESP-12F / ESP8266)
# Hardware revision: Rev A
# Variant:           full
# Contributor:       @jaycollett
# Source:            https://github.com/jaycollett/OpenIRBlaster
# License:           Apache 2.0
# Tested against:
#   HAIR:            <fill after testing>
#   HA Core:         <fill after testing>
#   ESPHome:         <fill after testing, 2026.5.0 minimum>
# Last verified:     <YYYY-MM-DD>
# Purpose:           RX+TX
# Hardware purchase: DIY, see hardware/ in the repo
# GPIO map:
#   GPIO5            IR RX (TSOP38238, inverted, pull-up)
#   GPIO14           IR TX (IR333-A via IRLML6344)
# Notes:
#   - ESP8266. No ESP8266 ir_rf_proxy reference config exists upstream.
#     Compile-tested on esp12e, see the repo for results.
#   - dump: is omitted deliberately. The proxy attaches to remote_receiver
#     directly and does not need it; on ESP8266 the decoders cost RAM.
#   - The legacy send_ir_raw service and openirblaster_learned event are
#     retained so the pre-HAIR path still works on the same firmware.
# ============================================================================

infrared:
  - platform: ir_rf_proxy
    name: "${friendly_name} TX"
    id: ir_proxy_tx
    remote_transmitter_id: ir_tx

  - platform: ir_rf_proxy
    name: "${friendly_name} RX"
    id: ir_proxy_rx
    receiver_frequency: 38kHz
    remote_receiver_id: ir_rx
```

Three changes to `remote_receiver` (`factory_flash.yaml:197-213`) worth making at the same time:

Drop `dump: raw`. It only drives log output. The proxy gets timings through `remote_base.attach_receiver` regardless, so removing it costs nothing and buys RAM on the chip that section 0 says has none to spare. If outcome 2 from priority zero happens, this is the first thing to cut anyway.

Raise `idle` from 25 ms. HAIR's references use 100 ms (`HAIR:esphome/generic-esp32-c3/generic-esp32-c3-minimal.yaml:87`). At 25 ms a long air-conditioner frame can be truncated mid-signal, which presents as a code that captures but does not replay. Climate matrices are something HAIR is good at, so this matters more under HAIR than it did before.

Consider `tolerance` 25% instead of 50%. HAIR uses 25%; 50% is loose enough to merge symbols on some protocols. Change this only if capture testing says so, since the current value is recorded in the repo as a stable result from prior testing.

---

## 3. Code library export tool

The priority deliverable for existing users. Nothing else here matters to them if the codes they learned one press at a time do not survive.

### 3.1 Answering the carrier_hz question first

The brief asked whether `.wig.json` can hold `carrier_hz` and what is lost if not. Good news: it holds it, and nothing is lost.

A wig has no `carrier_hz` field, no `pulses` field and no `timings` field. The payload is Pronto hex only (`HAIR:custom_components/hair/wig_format.py:1-14`). That looks like a problem until you look at what Pronto is. The second word of a Pronto preamble is the carrier, encoded as a divisor of a fixed reference frequency (`infrared_protocols/commands/pronto.py:13`, `:59-78`). Encoding `{pulses, carrier_hz}` into Pronto writes the carrier into the code, and any reader gets it back.

I measured the round trip rather than taking it on faith:

| carrier_hz in | preamble word | decoded back | error |
|---|---|---|---|
| 36000 | `0073` | 36045 Hz | +45 Hz (0.13%) |
| 38000 | `006d` | 38029 Hz | +29 Hz (0.08%) |
| 40000 | `0068` | 39857 Hz | -143 Hz (0.36%) |
| 56000 | `004a` | 56015 Hz | +15 Hz (0.03%) |

The analysis document says Pronto "preserves the carrier exactly" (`hair-analysis.md:366`). It preserves it to the quantization of the frequency word, which is within 0.36% across the whole IR band. A TSOP receiver has a passband thousands of Hz wide, so this is irrelevant in practice, and calling it exact is close enough for a user-facing sentence. It is not literally exact, so a converter should not assert byte-equality in a test.

The wider point is worth stating plainly, because it inverts the concern behind the question. Jay's existing codes carry real captured carrier values. New captures through `ir_rf_proxy` will not, because ESPHome delivers `modulation=None`. Exporting to `.wig.json` now, from the current library, is the one moment where those measured carriers are still in hand. Every code exported keeps its 36 kHz or 40 kHz forever. Every code re-learned through the new path after deleting the old library comes back at the 38 kHz default. That is an argument for doing the export before anything else, and for telling users not to delete their `.storage` file until they have run it.

### 3.2 Source schema, OpenIRBlaster

Storage lives at `<HA config>/.storage/openirblaster_<entry_id>`, one file per device, in Home Assistant's standard `Store` envelope with the payload under `data`. The envelope is built at `custom_components/openirblaster/storage.py:84-92`; the store is constructed at `storage.py:69-74` with `STORAGE_VERSION` and `STORAGE_MINOR_VERSION` from `const.py:35-36`, currently 1 and 1.

One code object, written at `storage.py:143-152`:

| Field | Type | Source | Meaning |
|---|---|---|---|
| `id` | string | `storage.py:144`, generated at `:211-227` | Lowercase slug from the original name, collision-suffixed `_2`, `_3`. Stable across renames |
| `name` | string | `storage.py:145` | Display name, mutable |
| `carrier_hz` | int | `storage.py:146` | Validated `> 0` at `learning.py:644-650`, typically 38000 |
| `pulses` | list[int] | `storage.py:147` | Signed microseconds, positive mark and negative space. Max 2000 (`const.py:22`) |
| `created_at` | ISO string | `storage.py:148` | UTC |
| `updated_at` | ISO string | `storage.py:149` | UTC |
| `tags` | list[string] | `storage.py:150` | May be empty |
| `notes` | string | `storage.py:151` | May be empty |

The device block also carries `config_entry_id`, `name`, `device_id` and an optional `last_learned` summary (`storage.py:259-263`). The whole format is already documented for users at `docs/storage-format.md`.

The sign and unit convention matches HAIR's encoder input contract exactly, which is why this conversion is arithmetic rather than interpretation.

### 3.3 Target schema, `.wig.json`

From `hair-analysis.md` section 8, cross-checked against the clone. A wig is one JSON object describing one remote. A minimal valid file:

```json
{
    "format": "hair-wig/3",
    "name": "Living Room TV",
    "signals": [
        {"alias": "Power", "pronto": "0000 006d 0004 0000 0156 00ac 0015 0017"}
    ]
}
```

Required on parse (`wig_format.py:537-711`): `format` matching `^hair-wig/(\d+)$`, a non-empty `name`, and a non-empty `signals` list whose entries each have a non-empty `alias` and a `pronto` that passes `validate_pronto`. Stamp `hair-wig/3`, which is what the current exporter writes for a flat wig (`wig_format.py:1037-1039`). Known per-signal keys are `alias`, `pronto`, `send_count`, `send_spacing_ms`, `ditto_count`, `bypass_protocol` (`wig_format.py:318-321`). For a converter, only `alias` and `pronto` matter; leave the rest out and let the parser apply defaults.

Unknown keys are tolerated and preserved through parse and re-serialize, at top level and per signal, which is the documented growth mechanism. A converter can safely stamp private keys.

Two schema slots worth using. `converted_from` and `converted_from_sha256` (`wig_format.py:120-121`) are the provenance pair: name the source tool and hash the `.storage` file it came from. `kind` comes from a fixed 27-word vocabulary (`wig_format.py:172-200`) and HAIR's own exporter refuses to guess one; the converter should leave it unset and let HAIR ask. File cap is 16 MB (`wig_format.py:102`), suffix `.wig.json`.

Import needs no HAIR code at all. Drop the file into `/config/hair/wigs/` over SSH or Samba and HAIR picks it up, which means the converter never has to integrate with anything.

### 3.4 The conversion

Use `ProntoCommand` from `infrared_protocols`, which ships with Home Assistant as a requirement of the `infrared` domain:

```python
from infrared_protocols.commands.pronto import ProntoCommand

pronto = ProntoCommand.from_raw_timings(code["pulses"], modulation=code["carrier_hz"]).to_pronto_hex()
# -> "0000 006d 0004 0000 0156 00ac 0015 0017 0015 0041 0015 05cb"
```

HAIR's own `raw_to_pronto(timings, frequency=...)` (`HAIR:custom_components/hair/ir_command.py:357`) does the same job and is 50 lines of dependency-free arithmetic that could be vendored. Prefer the `infrared_protocols` route for a standalone script, since it is already installed next to Home Assistant.

Four facts I verified by execution rather than reading:

Output case is lowercase and that is fine. `to_pronto_hex` builds from `bytes.hex()` (`pronto.py:81-83`), so words come out `006d` not `006D`. HAIR's validator accepts both (`pronto_validator.py:67`) and its canonical form lowercases anyway (`wig_format.py:1410-1420`).

The header is always `0000`, the modulated learned format, which is one of the two headers HAIR accepts (`0000` and `0100`). Compatible without special handling.

Odd-length pulse arrays fail. Pronto encodes burst pairs, so an array ending on a mark with no trailing space raises `ValueError: pronto timing data does not match the preamble burst pair counts`. I reproduced it with a 7-element array. Whether OpenIRBlaster ever writes odd-length arrays depends on how the firmware's `on_raw` handler terminates, which I did not trace. The converter should append a trailing gap when the length is odd and record it in the receipt rather than doing it silently.

Timings quantize, by up to 45µs on a 560µs interval, about 8 percent. Well inside NEC-family decode tolerance, which is 40 percent in the same library (`nec.py:15`). Worth spot-checking converted codes against real hardware before telling users the export is safe, particularly for long air-conditioner frames.

### 3.5 Field mapping

| OpenIRBlaster | wig | Handling |
|---|---|---|
| `data.device.name`, or the entry title | `name` | Required. Fall back to "OpenIRBlaster" plus the entry id |
| `code.name` | `signals[].alias` | Required, stripped, preserved verbatim |
| `code.pulses` + `code.carrier_hz` | `signals[].pronto` | Both encode into the one string. Carrier included |
| source file SHA-256 | `converted_from_sha256` | Provenance |
| (tool name) | `converted_from` | Provenance |
| `code.notes` | no per-signal target | Receipt file |
| `code.tags` | no target | Receipt file |
| `code.id` | no target | Dropped. Aliases are display names; HA entity ids are not portable |
| `code.created_at`, `code.updated_at` | no target | Dropped |
| (user choice) | `kind`, `brand`, `model` | Left unset. HAIR asks |

`notes` and `tags` are the only real loss, and it is small. They are per-code in OpenIRBlaster with no per-signal equivalent in a wig, which carries a single top-level `notes` string. Do not concatenate them into it; a merged blob attributed to no particular code is worse than nothing. Write a sidecar receipt listing code id, name, tags and notes, so anything worth keeping can be pasted back by hand. HAIR's own exporter does the same kind of skip accounting and surfaces it beside the export (`HAIR:custom_components/hair/wig_export.py:64-71`).

### 3.6 Grouping and delivery

One wig is one remote. An OpenIRBlaster library is a flat list per device, so a 40-code library covering three devices becomes one wig of 40 unrelated buttons unless the converter splits it. Offer `--group-by` with `file` (default, one wig per storage file, always correct if untidy), `tag` (one per distinct tag, remainder wig for untagged, best outcome for anyone who used tags) and `prefix` (split on the first name token, which suits the common "TV Power" / "TV Volume Up" habit). Users can re-split inside HAIR either way.

Ship it as `tools/openirblaster_to_wig.py` in this repo. No HAIR dependency, no HA import, reads a `.storage` file and writes wigs plus a receipt. Take a path in, write to a directory, never touch the source. Point the docs at the existing warning in `docs/storage-format.md` about HA caching `.storage` in memory.

Second, and not blocking: contribute a format probe and adapter to HAIR so users can drag the raw `.storage` JSON into its drop zone. HAIR dispatches on a prioritized probe list (`HAIR:custom_components/hair/wig_adapters.py:196-203`) already carrying SmartIR, Girr, Flipper and LIRC. An `openirblaster` probe is an easy match: a JSON object with `data.codes` whose entries have `id`, `pulses` and `carrier_hz`. That is the nicer experience and it puts OpenIRBlaster's name in HAIR's supported-formats list, which is free visibility for the hardware. It is also a PR on someone else's schedule, so the script must not wait for it.

---

## 4. Integration wind-down

Options with tradeoffs, not a decision. My recommendation is at the end.

### Option A: thin turnkey shim

Strip the integration to what HAIR does not cover. In practice: drop learning entirely, since HAIR's sniffer is better, and keep a read-only view of the existing library with its send buttons.

A v1.2.3 user upgrades, keeps their buttons, loses the Learn button, gains nothing. New codes go in HAIR, old codes stay in OpenIRBlaster storage, and the library is split permanently. Any HA change to the ESPHome event or service API is still Jay's to fix.

Nobody's dashboard breaks, which is the argument for it. Against: it preserves the exact thing this pivot exists to end, and guarantees every user ends up with two libraries.

This becomes the only viable option if priority zero fails, because a shim is then the only way Rev A hardware works at all.

### Option B: deprecate with a migration path

Ship a deprecation release that adds an `openirblaster.export_to_hair` service and an options-flow button writing the `.wig.json` from section 3 straight into `/config/hair/wigs/`, raises a persistent repair issue explaining the move and linking HAIR, and updates the README and HACS description. Everything else keeps working. After a stated grace period, stop feature work and archive.

A v1.2.3 user upgrades, nothing breaks, they get a notice and a one-click export. They install HAIR, import, and remove the old integration when ready. Nobody is forced and nobody re-learns a code.

Most work of the three, and most of that work is the export, which section 3 says to build regardless. The deprecation release is a thin wrapper over it.

### Option C: freeze

Stop releasing. README points at HAIR. Code stays on master and keeps working until HA breaks it.

A v1.2.3 user notices nothing until something breaks, then finds an unmaintained integration and no migration path. The dependency is on `esphome` event and service APIs, which are stable, so that could be a long time. Zero effort, worst experience, and it wastes the export by not putting it in front of anyone.

### Recommendation

Option B, shipped as **v1.2.4** rather than a 1.3. The version number is doing real work here: 1.3.0 signals a feature release and invites users to expect continued development, while a patch bump reads as what it is, a maintenance release whose entire content is the exit path. It also keeps the door open to a genuine 1.3.0 later if priority zero fails and option A becomes necessary.

Sequence it so the export ships before the deprecation notice, not with it. A repair issue telling users to migrate, pointing at a tool that does not exist yet, is worse than saying nothing.

### What the HACS entry should say

`hacs.json` currently reads `{"name": "OpenIRBlaster", "homeassistant": "2024.12.0"}`. Under option B the description should say in its first line that this is the integration for OpenIRBlaster hardware, that HAIR is the recommended way to use the device going forward, and that this integration exists to carry existing libraries across. It should not read as a competing general-purpose IR integration, because it stops being one.

One release mechanic, recorded in `docs/SESSION_KNOWLEDGE.md`: the Release workflow auto-tags and publishes from `manifest.json` on every master push, and CI fails any master push whose manifest version matches the latest release tag. Docs-only commits cannot be pushed alone; bundle them with a version bump.

### Version floors carried forward from the v2 research

These stop being OpenIRBlaster's problem under this plan, and become facts to state accurately in the docs, because they now describe what HAIR requires of a user rather than what Jay has to build against.

- The infrared receiver API landed in HA 2026.6.0, not 2026.4.0. I verified this by fetching `homeassistant/components/infrared/__init__.py` at every release tag: `async_subscribe_receiver` is absent at 2026.4.0 and 2026.5.0 and present from 2026.6.0. HAIR's `hacs.json` floors at 2026.4.0, which is correct for its emitter-only and bridge paths but not for native capture. Recommend 2026.9.0 in OpenIRBlaster's own docs.
- Python 3.14 is a hard floor for anything importing `infrared_protocols` (`requires-python = ">=3.14"`, verified from PyPI metadata). HA 2026.6+ requires it anyway. This repo's CI runs Python 3.12 (`docs/SESSION_KNOWLEDGE.md`), so the export tool's test job needs 3.14 even though the shipped integration does not.
- `infrared-protocols` went from 1.1.0 to 10.1.0 in five months, ten majors, with two breaks I verified in code: `get_raw_timings()` changed return type, and the code factory moved from a module-level `make_command` to an `Enum.to_command` method. Core owns the pin, so pinning is unavailable. The export tool uses only `ProntoCommand.from_raw_timings` and `to_pronto_hex`, which is the narrowest possible surface, and vendoring the 50 lines of Pronto arithmetic is the escape hatch if that surface moves.

---

## 5. README and positioning

The repo currently presents as a Home Assistant integration that happens to have hardware. Invert that.

Open by saying what the hardware is: an open-source ESP8266 IR blaster for Home Assistant, with schematic, board, BOM, enclosure and prebuilt firmware in the repo, linking the rendered schematic PNG so people can see it without Eagle. Then how to get one, which today means building it and should say so honestly until a fab package exists. Then how to flash it, where `dashboard_import` already gives a one-click path from the ESPHome dashboard.

Then the part that changes. Point at HAIR as the recommended software, link its repo and HACS entry, and link the OpenIRBlaster ESPHome config once contributed. Say plainly that the device registers as a standard Home Assistant infrared emitter and receiver, so it works with anything built on that platform. That one sentence is worth more than a feature list, because it says the hardware is not locked to a single piece of software, which is the whole argument for owning hardware instead of an integration.

Close with a short legacy section: what the integration was, that it still works, that it is deprecated in favour of HAIR, and where the export tool lives.

Two distribution moves beyond this repo. Contribute the config to HAIR, which preserves contributor attribution permanently in the header. Also submit to `esphome/infrared-proxies`, the Home Assistant team's own IR proxy config repo, which currently lists one device. Being the second entry there, and the only ESP8266 one, is real visibility for a small hardware project.

Two hygiene items that make the repo read as hardware rather than software with attachments: add a hardware licence distinct from the software `LICENSE`, and publish the fab package from item 3 below.

---

## 6. Ordered plan

Effort in developer-days. Item 0 gates items 2 and 4 and shapes item 5.

### 0. Compile and run ir_rf_proxy on esp12e, 0.5 day

Already running in parallel. Build `factory_flash.yaml` plus the section 2.2 block for `board: esp12e` against ESPHome 2026.5.0+. Confirm it compiles, fits, flashes, produces two `infrared` entities, captures and sends. Record the result in `docs/SESSION_KNOWLEDGE.md` either way, since it is the kind of finding that is expensive to rediscover.

### 1. Code library export tool, 2 days

`tools/openirblaster_to_wig.py` per section 3. Storage reader, Pronto encoding with the odd-length guard, three grouping modes, receipt file, tests against a real exported library on Python 3.14. Independent of item 0, so start it immediately and in parallel. It is what users need most and it works regardless of how the compile goes.

### 2. ESPHome config and firmware release, 1 day

Depends on item 0. Add the `infrared:` block, drop `dump:`, raise `idle`, decide `tolerance` from capture testing, fill the header's tested-against versions, bump `esphome.project.version` from `0.5.0` (`factory_flash.yaml:14`), rebuild `factory_flash.bin`, update `docs/firmware-and-esphome.md`. Keep the legacy service, event and replay path in place.

### 3. Fab package, 1 day

Generate gerbers and drill files from `Open_IR_Blaster.brd`, commit under `hardware/fab/` with a short README naming stackup and fab-house settings. Add a hardware licence. Consider exporting a KiCad project alongside the Eagle files. This is the single change that most turns the repo into something other people can build, and it is the one item here that nobody else in this ecosystem can do for Jay.

### 4. Contribute configs upstream, 0.5 day

Depends on items 0 and 2. PR to HAIR with a filled header, and to `esphome/infrared-proxies`. Small PRs into other people's repos, so open them early and expect them to land on someone else's schedule.

### 5. Deprecation release v1.2.4, 1.5 days

Option B. Wire the item 1 export into an `openirblaster.export_to_hair` service and an options-flow entry writing into `/config/hair/wigs/`, add the deprecation repair issue and strings, update `hacs.json`. Ship after item 1, never before. If item 0 failed, this becomes option A instead and the scope changes.

### 6. README and positioning, 1 day

Section 5. README, `docs/README.md`, the HACS description, and a `docs/SESSION_KNOWLEDGE.md` entry recording why the project pivoted and what the compile found.

### Totals

| Scope | Items | Days |
|---|---|---|
| Everything | 0 through 6 | 7.5 |
| If item 0 fails, no firmware path | 0, 1, 3, 5 as option A, 6 | 5.5 |
| Minimum that gets users their codes | 0, 1, 6 | 3.5 |

Item 1 is worth doing whatever item 0 returns, and it should start now rather than after. Item 3 is worth doing whatever happens to any of the software, because it is the part of this repo nobody else can replace.
