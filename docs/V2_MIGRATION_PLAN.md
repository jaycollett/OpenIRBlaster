# OpenIRBlaster v2.0 migration plan

Status: proposal, awaiting approval. No source files changed.
Written 2026-09-19 against v1.2.3 (commit 6e8f4ad, branch master, clean).

This plan moves OpenIRBlaster off its private ESPHome transport (the `esphome.openirblaster_learned` event plus the `send_ir_raw` user service) and onto Home Assistant's `infrared` entity domain. The storage layer, the code library, stable code IDs and the per-code button entities stay. Only the transport and the entity wiring around it change, plus a new presets feature layered on top.

## Verification notes, read these first

Everything below about Jay's current code was read from the working tree and carries a `file:line` reference. Everything about the new API was read from source, not from a search summary:

- `homeassistant/components/infrared/` as installed in `.venv` (HA 2026.4.3, Python 3.14.7).
- `homeassistant/components/infrared/{__init__,entity,helpers,const}.py` at tag `2026.9.0`, fetched from `raw.githubusercontent.com/home-assistant/core`.
- `homeassistant/components/esphome/infrared.py` at tags `2026.4.3` (installed) and `2026.9.0`.
- `infrared_protocols` 10.1.0, downloaded from PyPI, unpacked and imported under Python 3.14.7 for live introspection.

Three corrections to the assumptions this work started from. They change the plan, so they are up top.

### Correction 1: the receiver API did not ship in 2026.4

The brief says "require HA 2026.4+". That floor does not work. The `infrared` domain shipped in 2026.4, but at 2026.4 it was emitter only. Verified by fetching `homeassistant/components/infrared/__init__.py` at each release tag and grepping for `async_subscribe_receiver`:

| HA tag | `async_subscribe_receiver` present | `helpers.py` present | pinned library |
|---|---|---|---|
| 2026.4.0 | no | no (404) | infrared-protocols==1.1.0 |
| 2026.5.0 | no | no (404) | infrared-protocols==2.0.0 |
| 2026.6.0 | yes | yes | infrared-protocols==5.6.1 |
| 2026.7.0 | yes | yes | infrared-protocols==6.3.0 |
| 2026.8.0 | yes | yes | infrared-protocols==8.2.1 |
| 2026.9.0 | yes | yes | infrared-protocols==9.0.0 |
| dev | yes | yes | infrared-protocols==10.1.0 |

The installed 2026.4.3 copy confirms it independently: its `__all__` is exactly `["DOMAIN", "InfraredEntity", "InfraredEntityDescription", "async_get_emitters", "async_send_command"]`, there is no `entity.py`, no `helpers.py`, no `InfraredReceivedSignal` and no receiver base class anywhere in the package.

The real floor for capture is HA 2026.6.0. My recommendation is to set the floor at 2026.9.0 instead, for reasons in Correction 2.

### Correction 2: the library API moved under the domain between 2026.4 and 2026.9

`infrared-protocols` went from 1.1.0 to 10.1.0 in about five months, ten major versions. That is not cosmetic. Two breaks are visible in code I read directly:

`Command.get_raw_timings()` changed its return type. At HA 2026.4.3, `esphome/infrared.py:38-42` has to unpack timing objects:

```python
timings = [
    interval
    for timing in command.get_raw_timings()
    for interval in (timing.high_us, -timing.low_us)
]
```

At HA 2026.9.0, `esphome/infrared.py:50` just passes it through, because `get_raw_timings()` now returns a flat `list[int]` of signed microseconds:

```python
timings = command.get_raw_timings()
```

The code lookup entry point changed too. At HA 2026.4.3, `lg_infrared/entity.py` imports `make_command` as a module-level function:

```python
from infrared_protocols.codes.lg.tv import LGTVCode, make_command as make_lg_tv_command
```

At 10.1.0 there is no module-level `make_command`. The factory is a method on the enum: `LGTVCode.POWER.to_command(repeat_count=0)`. I confirmed this by importing the extracted wheel.

Both breaks land squarely on the presets feature. Targeting 2026.6 means writing against a library API two majors old with no way to pin it, because core owns the pin. Targeting 2026.9 costs users nothing real (it is the current release as of today) and gets the API shape the presets code will actually be written against.

### Correction 3: Python 3.14 is the real floor, and the project already runs it

`infrared-protocols` declares `requires-python = ">=3.14"` (verified from the PyPI JSON metadata for 10.1.0). Depending on `infrared` inherits that floor. CLAUDE.md says the project targets Python 3.12+ and `hacs.json` claims `"homeassistant": "2024.12.0"`. Both have to move.

Practically this is less painful than it sounds. HA 2026.6+ already requires Python 3.14 in its own right, so any user on a supported HA is already there, and the local `.venv` is already 3.14.7. The cost falls on CI, which `docs/SESSION_KNOWLEDGE.md` records as running Python 3.12 with pinned requirements.

Stated plainly, a v2.0 user needs: Home Assistant 2026.9.0 or newer, which implies Python 3.14, plus ESPHome 2026.1.0 or newer on the device (recommend 2026.5.0+, see the risk register).

---

## a. Current state

### The ESPHome learned event

The event name is defined once and consumed in one place.

| What | Where |
|---|---|
| Event name constant | `const.py:18` (`EVENT_LEARNED = "esphome.openirblaster_learned"`) |
| Bus subscription, armed per session | `learning.py:246-248` |
| Event handler | `learning.py:477-593` |
| MAC vs device_id filtering | `learning.py:489-567` |
| Dangling-MAC firmware repair | `learning.py:63-67`, `learning.py:499-523` |
| Payload attribute keys | `const.py:47-54` |
| Payload parse and validation | `learning.py:595-695` |
| Firmware side that fires it | `hardware/firmware/factory_flash.yaml:64-77`, `:261-266` |

The handler is 117 lines, and roughly 80 of those exist only because a bus event carries no identity. It has to decide whether the event belongs to this device by comparing a MAC that older firmware sometimes returned as garbage from a dangling `c_str()` pointer (`learning.py:63-67` documents the bug, `learning.py:499-517` detects it and raises a repair issue).

### The capture-marker replay path

A second capture path exists purely to recover events lost on a dropped ESPHome API socket. It watches a `text_sensor` whose value replays on reconnect, waits 500ms, and if no event arrived it calls a second ESPHome service to re-fire the event.

| What | Where |
|---|---|
| Marker constants and grace period | `learning.py:42-61` |
| Marker entity resolution (two strategies) | `learning.py:325-385` |
| Marker state-change handler | `learning.py:387-427` |
| Wait-then-replay task | `learning.py:429-447` |
| Replay service call | `learning.py:449-475` |
| Replay task tracking and cancellation | `learning.py:130-133`, `learning.py:697-704` |
| Double-commit guard the path forced | `learning.py:121-126`, `learning.py:611-614` |

### The send_ir_raw service call

Three call sites, all with the same shape, plus a four-layer discovery mechanism behind them.

| What | Where |
|---|---|
| Send last learned | `button.py:398-434` |
| Send a stored code | `button.py:478-511` |
| `send_code` service | `services.py:234-295` (the call itself at `:266-285`) |
| Cached service-name lookup | `helpers.py:193-209` |
| Discovery at setup, four priorities | `helpers.py:119-190` |
| Cross-entry claim tracking | `helpers.py:96-116` |
| Ambiguity error type | `helpers.py:25-31` |
| Missing-service repair pair | `helpers.py:34-59` |
| Config-flow discovery | `config_flow.py:228-281` |
| Firmware side | `hardware/firmware/factory_flash.yaml:30-43` |

`docs/SESSION_KNOWLEDGE.md` records why the claim tracking exists: with two blasters and one offline at boot, a bare `*_send_ir_raw` pattern match bound the offline entry to the other device's service and transmitted from the wrong hardware.

### carrier_hz

Present in 15 files or call chains. Full inventory:

- Storage schema and writes: `storage.py:133`, `:146`, `:166`, `:179-180`
- Capture model and validation: `learning.py:76`, `:588`, `:598`, `:632-650`, `:681`
- Sends and button construction: `button.py:95`, `:121`, `:339`, `:420`, `:445`, `:451`, `:496`
- Services: `services.py:77`, `:192`, `:245`, `:254`, `:271`, `:291`, `:413`, `:446`
- Options flow save and its form text: `config_flow.py:534`, `:579`
- Event entity attributes: `event.py:112`, `:129`
- Diagnostics: `diagnostics.py:58`
- User-visible strings: `strings.json:45`, `:158`
- Service schema bounds (30000 to 56000 Hz): `services.yaml:47-54`
- Firmware default and plumbing: `factory_flash.yaml:5`, `:119`, `:243`, `:266`

Today it is required and validated as a positive int (`learning.py:644-650`), and the notification text prints it (`learning.py:723`).

### The learning state machine

States are string constants at `const.py:25-30`, the 30 second default at `const.py:21`.

| Transition | Where |
|---|---|
| Entry point, terminal-state reset, synchronous ARMED claim | `learning.py:175-280` |
| Timeout scheduling via `async_call_later` | `learning.py:273-275` |
| Listener and timeout teardown, idempotent | `learning.py:282-298` |
| Capture commit, IDLE/ARMED to RECEIVED | `learning.py:672-695`, `learning.py:706-742` |
| Timeout handler, ARMED to TIMEOUT | `learning.py:744-792` |
| User cancel, ARMED to CANCELLED | `learning.py:794-816` |
| Validation cancel, ARMED to CANCELLED | `learning.py:818-853` |
| Reset to IDLE | `learning.py:855-877` |
| Unload cleanup | `learning.py:879-904` |
| Callback fan-out to entities | `learning.py:146-173` |

The one-session lock is two things working together. First, exactly one `LearningSession` object is constructed per config entry (`__init__.py:356-362`, held at `data.py:23`), so "one session per device" is really "one session per config entry". Second, the ARMED claim at `learning.py:218` is set before the first `await`, so a concurrent `async_start_learning` hits the rejection at `:190-194` rather than overwriting the first session's unsubscribe callable.

The device also has a hardware-level arm step: a `switch` entity that puts the firmware into learning mode. Turned on at `learning.py:231-243`, off at `learning.py:313-323` with five call sites, resolved at config time by `config_flow.py:174-226`, and force-reset at setup if a previous run left it on (`__init__.py:420-453`).

### Module map, current

| Module | Lines | Role |
|---|---|---|
| `__init__.py` | 496 | Setup, MAC back-fill, device registry, legacy migrations, orphan sweep |
| `learning.py` | 904 | State machine, event listener, replay path, timeout |
| `config_flow.py` | 677 | ESPHome device discovery, reconfigure, options flow (save, delete) |
| `button.py` | 512 | Learn, send-last, per-code buttons |
| `services.py` | 481 | Six integration services |
| `sensor.py` | 239 | Three last-learned diagnostic sensors |
| `storage.py` | 271 | JSON persistence, slug IDs, migration hook |
| `helpers.py` | 209 | ESPHome service discovery, repairs, entity cleanup |
| `event.py` | 133 | `code_activity` event entity |
| `text.py` | 103 | Code Name input |
| `diagnostics.py` | 91 | Redacted entry dump |
| `data.py` | 30 | Runtime dataclass |
| `const.py` | 84 | Constants |

Tests: 137 test functions across 12 files, 4,192 lines.

---

## b. Target state

### Module fate

| Module | Fate |
|---|---|
| `storage.py` | Survives, extended. Schema v1 to v2, `carrier_hz` nullable, new `source` and `preset` fields |
| `learning.py` | Survives, roughly halved. Event listener, marker/replay path, MAC filtering and switch control all go; subscription lifecycle replaces them |
| `button.py` | Survives, transport swapped. `CodeButton` and `SendLastButton` call `async_send_command` |
| `services.py` | Survives, transport swapped in `send_code`, new `add_preset` service |
| `config_flow.py` | Heavily rewritten. Emitter and receiver entity pickers replace ESPHome device discovery. New preset-picker options steps |
| `sensor.py` | Survives unchanged in shape |
| `event.py` | Survives, `carrier_hz` attribute becomes nullable |
| `text.py` | Survives unchanged |
| `diagnostics.py` | Survives, new fields |
| `data.py` | Survives, `esphome_service_name` field replaced by emitter/receiver entity IDs |
| `helpers.py` | Mostly deleted. Everything ESPHome-specific goes; `async_remove_code_entities` stays |
| `__init__.py` | Survives, shrinks. MAC back-fill and service discovery go; a config-entry migration is added |
| `commands.py` | New. `RawCommand`, the `Command` subclass that carries stored pulses |
| `presets.py` | New. Codeset enumeration and preset-to-command resolution |

### The send path

`infrared.async_send_command(hass, entity_id, command, context=None)` takes an `infrared_protocols.commands.Command`, not raw timings. Verified at HA 2026.9.0 `infrared/helpers.py:35-66`. So the integration needs a `Command` subclass that carries a stored pulse array verbatim.

`Command` is a plain ABC with no machinery (verified, `infrared_protocols/commands/__init__.py` at 10.1.0):

```python
class Command(abc.ABC):
    repeat_count: int
    modulation: int
    def __init__(self, *, modulation: int, repeat_count: int = 0) -> None: ...
    @abc.abstractmethod
    def get_raw_timings(self) -> list[int]: ...
```

So a new `commands.py` holds roughly this:

```python
DEFAULT_MODULATION_HZ = 38000

class RawCommand(Command):
    """A stored pulse array replayed verbatim."""

    def __init__(self, timings, *, modulation=None, repeat_count=0):
        super().__init__(
            modulation=modulation or DEFAULT_MODULATION_HZ,
            repeat_count=repeat_count,
        )
        self._timings = list(timings)

    def get_raw_timings(self):
        return list(self._timings)
```

The sign convention already matches. Both `Command.get_raw_timings` and the stored `pulses` array use positive microseconds for mark and negative for space (`docs/storage-format.md`, code fields table), so no transformation is needed.

There is an alternative worth naming and rejecting. `infrared_protocols.commands.pronto.ProntoCommand.from_raw_timings(timings, modulation=None)` exists and does exactly this job, defaulting to 38000 Hz when modulation is None. I tested a round trip under Python 3.14.7 with the extracted 10.1.0 wheel:

```
in:  [9000, -4500, 560, -560, 560, -1690, 560, -560, ...]
out: [8993, -4523, 552,  -605, 552, -1709, 552,  -605, ...]
```

Worst-case drift 45µs per interval, and `cmd.modulation` reads back as 38029 rather than 38000, because Pronto quantizes timings against a fixed reference frequency. NEC decoding tolerance in the same library is 40 percent (`commands/nec.py:15`), so it would probably work. It is still a lossy round trip on data that used to be replayed byte for byte, on a feature whose whole value is byte-for-byte fidelity. Use `RawCommand`. Keep `ProntoCommand` in mind only if a future import/export feature wants a portable text format.

### The capture path and the state machine

`async_subscribe_receiver(hass, entity_id_or_uuid, signal_callback) -> CALLBACK_TYPE` (verified, HA 2026.9.0 `infrared/helpers.py:69-105`). It raises `HomeAssistantError` with translation key `receiver_not_found` when the entity is missing or is not an `InfraredReceiverEntity`, and `component_not_loaded` when the domain is not set up. The callback receives `InfraredReceivedSignal(timings: list[int], modulation: int | None = None)` (verified, `infrared/entity.py:30-35`).

Nothing is fired on the event bus. The receiver's own state does change to a new timestamp on every capture, so a YAML automation can see that a signal arrived, but the timings are not in the state or in any attribute.

State mapping:

| State | Today | Under v2 |
|---|---|---|
| IDLE | No listeners, no timeout | Same. No subscription held |
| IDLE to ARMED | Claim state, turn on the firmware switch, subscribe to the bus, resolve and subscribe to the marker sensor, schedule `async_call_later` | Claim state (unchanged, still before the first await), call `async_subscribe_receiver` on the selected receiver, schedule `async_call_later`. No switch, no marker |
| ARMED to RECEIVED | Filter the event by MAC or device_id, parse `pulses_json`, validate carrier, commit | Callback fires with an already-typed `InfraredReceivedSignal`. Validate length only, commit |
| ARMED to TIMEOUT | Teardown, switch off, notify | Teardown, notify. No switch |
| ARMED to CANCELLED | Teardown, switch off, notify | Teardown, notify. No switch |
| RECEIVED to SAVED | Storage write, dispatcher signal | Unchanged |
| any to IDLE | `async_clear_pending` | Unchanged |

Where the subscription lives: created inside `async_start_learning` immediately after the ARMED claim, stored on the session as `self._unsub_receiver`, released in `_teardown_listeners_and_timeout` (`learning.py:288-298` today). That is the same lifetime the bus listener has now, so the teardown call sites do not move.

I am deliberately not using `InfraredReceiverConsumerEntity` (HA 2026.9.0 `infrared/helpers.py:174-229`), even though the research report recommends it. It is an `Entity` base that subscribes for the entity's whole lifetime and manages resubscription on receiver availability changes. OpenIRBlaster wants a subscription that exists only during a 30 second armed window, so a permanently subscribed entity would have to filter out every stray IR signal in the room and would defeat the timeout. The direct helper is the right fit. What is worth borrowing from the consumer base is its availability handling: track the receiver entity's state with `async_track_state_change_event` while armed, and fail the session with a clear reason if the receiver goes unavailable mid-window rather than silently timing out.

The 30 second timeout mechanism does not change. `async_call_later` at `learning.py:273-275` is transport-agnostic, and the `_capture_finalized` guard at `learning.py:754` that prevents a capture landing at the deadline from being stomped by the timeout path stays exactly as it is.

### The new locking model

This is the one place where the design genuinely has to change rather than shrink.

Today the lock is implicit. One config entry means one ESPHome device means one `send_ir_raw` service and one learning switch. Under the infrared domain, a config entry selects an emitter entity and a receiver entity from a pool. Several OpenIRBlaster entries may point at the same receiver, and a single device advertising both capabilities produces two separate `infrared` entities.

Three locking layers, stated explicitly:

1. Per-entry session lock. Unchanged. The synchronous ARMED claim before the first await (`learning.py:218`) still rejects a second concurrent start on the same entry.

2. Per-receiver exclusivity, new. Two entries armed against the same receiver would both receive every signal and both commit it, so two codes get saved from one button press. The fix is a module-level registry in `hass.data[DOMAIN]["armed_receivers"]`, a `dict[str, str]` mapping receiver entity ID to the entry ID holding it. `async_start_learning` claims the receiver synchronously in the same block as the ARMED state claim, and fails with a `ServiceValidationError` naming the conflicting entry when it is already held. The teardown releases it. Because the claim and the state claim happen in the same synchronous block, there is no window between them.

3. Emitter concurrency, none needed. Sends are fire and forget and the emitter serializes them itself. Nothing to guard.

One consequence worth stating: a user who wants two entries against one physical blaster (say, one library per room) can now do that, and learning on one blocks learning on the other for the duration of the window. That is correct behavior, and the error message should say so.

---

## c. Storage schema migration

### Version bump

`STORAGE_VERSION` goes 1 to 2 (`const.py:35`). `STORAGE_MINOR_VERSION` resets to 1 (`const.py:36`). The migration goes in `OpenIRBlasterStore._async_migrate_func` (`storage.py:33-59`), which today is an identity function that rejects anything it does not recognize.

Major rather than minor because `carrier_hz` changes from required to nullable, and a v1.x integration reading a v2 file would hit `code[ATTR_CARRIER_HZ]` at `button.py:95` and crash on a `None`. The rejection branch at `storage.py:54-59` already prevents that, and bumping major is what makes it fire.

### Field changes

Per code object:

| Field | v1 | v2 | Migration |
|---|---|---|---|
| `id` | string, required | unchanged | untouched |
| `name` | string, required | unchanged | untouched |
| `carrier_hz` | int, required, > 0 | `int \| None` | existing values preserved verbatim |
| `pulses` | list[int], required, max 2000 | `list[int] \| None` | preserved; None only for preset codes |
| `created_at`, `updated_at` | ISO string | unchanged | untouched |
| `tags`, `notes` | list / string | unchanged | untouched |
| `source` | absent | `"learned" \| "preset"` | back-filled to `"learned"` for every existing code |
| `preset` | absent | object or absent | never present after migration |

Per device block: unchanged. `config_entry_id`, `name`, `device_id`, `last_learned` all stay. `device_id` becomes vestigial once ESPHome discovery is gone, but leaving it costs nothing and removing it would break `docs/storage-format.md` for no gain.

The migration function body:

```python
async def _async_migrate_func(self, old_major_version, old_minor_version, old_data):
    if old_major_version > STORAGE_VERSION:
        raise ValueError(...)  # existing forward-incompatible guard

    data = old_data
    if old_major_version < 2:
        for code in data.get("codes", []):
            code.setdefault(ATTR_SOURCE, SOURCE_LEARNED)
        data["version"] = 2

    return data
```

Note it is `setdefault`, not assignment, and it does not touch `carrier_hz`. Nothing is dropped and nothing is rewritten. A v1 file that has been hand-edited per `docs/storage-format.md` migrates cleanly as long as it is valid v1. This is also idempotent, so a partially migrated file (interrupted write) converges.

### How carrier_hz becomes nullable without breaking existing entries

Nullability is a read-side change, not a write-side one. Existing entries keep their captured integer and keep sending at it, because `RawCommand(timings, modulation=code["carrier_hz"])` passes the stored value straight through. New captures from the infrared path store `None` and `RawCommand` substitutes 38000.

The read sites that need a None guard:

- `button.py:95`, `:121`, `:445-451`, `:496`: `CodeButton` takes `carrier_hz` positionally and hands it to the service call. Change the type to `int | None` and pass it to `RawCommand`.
- `services.py:77`: `vol.Optional(ATTR_CARRIER_HZ): cv.positive_int` stays as-is, since an explicit override is still a positive int when supplied.
- `services.py:254`, `:271`, `:291`: already uses `.get()` with a None default, so only the downstream call changes.
- `event.py:112`, `:129`: attribute becomes nullable. No code change needed, the dicts already tolerate None.
- `diagnostics.py:58`: already `.get()`.
- `strings.json:45`: the options-flow save form prints `Carrier: {carrier_hz} Hz`. Needs a variant for the unknown case, or set the placeholder to "38 kHz (default)" when None.
- `learning.py:632-650`: the whole carrier coercion and validation block goes away. `InfraredReceivedSignal.modulation` is already `int | None`.

### Preset codes in storage

A preset code is a stored code with `source: "preset"`, `pulses: null`, `carrier_hz: null`, and a `preset` object that names the library symbol:

```json
{
  "id": "living_room_tv_power",
  "name": "Living Room TV Power",
  "source": "preset",
  "carrier_hz": null,
  "pulses": null,
  "preset": {
    "module": "infrared_protocols.codes.lg.tv",
    "enum": "LGTVCode",
    "member": "POWER",
    "library_version": "10.1.0"
  },
  "created_at": "...",
  "updated_at": "...",
  "tags": [],
  "notes": ""
}
```

Timings are resolved at send time, never stored. Storing them would freeze a snapshot of whatever the library said on the day the preset was added, and would silently diverge from the library on every HA upgrade. Resolving at send time means an upstream fix to a brand's codes reaches the user for free.

Whoever reads a code decides by `source`. Learned codes go through `RawCommand`, preset codes go through `presets.resolve()`. One dispatch point in `commands.py` and every caller stays the same shape.

### Code IDs stay stable

The rule does not change: `_generate_unique_id` (`storage.py:211-227`) slugifies the original name and appends `_2`, `_3` on collision, and rename only touches `name` (`storage.py:177-178`). The entity unique ID is `{entry_id}_{code_id}` (`const.py:79`), and `SIGNAL_CODE_RENAMED` updates the button's display name in place (`button.py:470-476`).

Preset codes use the same generator against the user-supplied display name. The library symbol lives in the `preset` object and never leaks into the ID, so the same preset added under two names gets two independent IDs, and re-picking a different library command for the same code (should that ever be supported) does not orphan the entity.

---

## d. Presets

This section is written against `infrared_protocols` 10.1.0, which I downloaded, unpacked and imported under Python 3.14.7. Every claim here was executed, not read. What I could not verify is which version core will pin when Jay actually ships, which is the one real uncertainty and is in the risk register.

### What is actually in the library

Measured, not estimated:

- 17 brand directories under `infrared_protocols/codes/`: dyson, edifier, general_electric, generic, lg, marantz, nec, nedis, osram, panasonic, persang, philips, pioneer, samsung, sharp, sony, vizio.
- 39 enum classes across those brands.
- 37 of them expose `to_command`. The two that do not are `edifier.models.EdifierCommandSet` and `edifier.models.EdifierModel`, which are `StrEnum` mapping tables rather than code tables and must be filtered out.
- 1,178 enum members across the 37 usable classes. Per brand: lg 222, vizio 161, sony 152, generic 131, edifier 116, marantz 68, nec 50, samsung 49, philips 45, panasonic 36, pioneer 36, sharp 30, osram 24, persang 21, dyson 18, nedis 11, general_electric 8.

### Enumeration, with a trap

`pkgutil.iter_modules` and `pkgutil.walk_packages` both return an empty list for `infrared_protocols.codes`. I verified this. The brand directories have no `__init__.py`, so they are namespace packages, and pkgutil's file finder only reports a subdirectory as a package when it contains an `__init__` file.

`importlib.resources` works:

```python
import importlib
import importlib.resources as res

root = res.files("infrared_protocols.codes")
brands = sorted(p.name for p in root.iterdir() if p.is_dir() and not p.name.startswith("__"))
# then walk each brand dir for *.py, import, and collect Enum subclasses
# whose __module__ matches and which have a `to_command` attribute
```

That is the enumeration I ran to get the numbers above. It is filesystem traversal of someone else's package layout, which is not a supported API. Cache the result in `hass.data` on first use and treat a traversal failure as "no presets available" rather than a setup failure.

### Calling to_command

Five distinct signatures exist across the 37 classes:

| Signature | Classes |
|---|---|
| `(self) -> Command` | 8 |
| `(self, repeat_count: int = 0) -> Command` | 25 |
| `(self, repeat_count: int = 0, *, toggle: int = 0) -> Command` | 2 |
| `(self, switch: int = 1) -> Command` | 1 |
| `(self) -> Command` (string-annotated) | 1 |

So the resolver calls `member.to_command()` with no arguments, always. Every signature has defaults for everything. Do not pass `repeat_count` positionally or by keyword, because eight classes do not accept it. If repeat support is wanted later, inspect the signature first.

Verified working, end to end:

```python
>>> from infrared_protocols.codes.lg.tv import LGTVCode
>>> cmd = LGTVCode.POWER.to_command()
>>> type(cmd)
<class 'infrared_protocols.commands.nec.NECCommand'>
>>> cmd.modulation, cmd.repeat_count, len(cmd.get_raw_timings())
(38000, 0, 67)
```

### The picker flow

Three options-flow steps, a new branch from the existing menu at `config_flow.py:496-499`:

1. `async_step_add_preset_brand`: dropdown of the 17 brand names, title-cased for display.
2. `async_step_add_preset_device`: dropdown of enum classes within the brand, labeled by module and class (`lg.tv / LGTVCode`). Brands with one class skip straight through.
3. `async_step_add_preset_command`: dropdown of the members, plus a required `name` text field defaulting to a humanized member name (`POWER_ON` becomes "Power On"). Same duplicate-name check as the save path (`storage.py:122-128`).

On submit, write the code with `source: "preset"` and dispatch `SIGNAL_CODE_ADDED` (`const.py:73`), which already causes the button platform to add a `CodeButton` and the sensors to refresh (`button.py:110-133`). No entry reload.

A parallel `openirblaster.add_preset` service takes `config_entry_id`, `brand`, `device`, `command`, `name` so scripts can bulk-add.

### What happens when the pinned library changes

The failure mode is a stored `preset` object whose module, enum class or member no longer exists after a HA upgrade.

`presets.resolve(preset)` returns a `Command` or raises `PresetUnavailable`. On failure:

- `CodeButton.async_press` logs the specific missing symbol and raises a repair issue (translation key `preset_unavailable`) naming the code and the symbol. It does not crash the entity or the entry.
- The button stays registered and stays visible. Deleting it automatically would destroy the user's name, tags and notes over what may be a transient packaging problem.
- Diagnostics lists unresolvable presets so a bug report carries the evidence.
- The stored `library_version` is informational only, recorded at add time so a support conversation can compare it against the running pin. It is never used to gate resolution.

An HA upgrade that changes the codeset should not reload or rewrite storage. Resolution is lazy, at send time, and that is the whole point.

---

## e. Entity model

### What changes

| Entity | Today | Under v2 |
|---|---|---|
| Learn button (`button.py:159-377`) | Reads Code Name text, arms the session, auto-saves | Same behavior. Also unavailable when the configured receiver is missing or unavailable |
| Send Last button (`button.py:380-434`) | Calls `esphome.<device>_send_ir_raw` | Calls `infrared.async_send_command` with a `RawCommand` |
| Per-code button (`button.py:437-511`) | Holds `carrier_hz` and `pulses`, calls the ESPHome service | Holds the code dict, dispatches on `source`, calls `async_send_command`. Unavailable when the emitter is unavailable |
| Last-learned sensors (`sensor.py`) | Three diagnostic sensors, storage-backed | Unchanged |
| Code Name text (`text.py`) | Input for the Learn button | Unchanged |
| `code_activity` event (`event.py`) | `code_learned` and `code_saved` | Unchanged shape. `carrier_hz` attribute becomes nullable, a `source` attribute is added to `code_saved` |

### Availability

This is genuinely new. Today entities are always available, and a dead device surfaces as a repair issue after a failed send (`helpers.py:34-53`). Under v2 the emitter and receiver are real HA entities with real states, so availability is observable up front.

Borrow the pattern from `infrared/helpers.py:111-141` (`InfraredConsumerEntity._async_track_availability`) rather than the base class itself: set initial availability from `hass.states.get(emitter_entity_id)`, then `async_track_state_change_event` on it, flipping `_attr_available` when it crosses `unavailable`. Send buttons track the emitter, the Learn button tracks the receiver. That replaces the `esphome_service_missing` repair entirely, and it is a better experience: the button greys out before the user presses it.

### Selecting among several emitters and receivers

`async_get_emitters(hass)` and `async_get_receivers(hass)` each return a list of entity IDs and return `[]` when the domain is not loaded (verified, HA 2026.9.0 `infrared/__init__.py:78-103`). They are filtered by `isinstance` against the two base classes, so a device advertising both capabilities appears in both lists as two distinct entities.

Selection is a user decision made in the config flow, not a heuristic. Two entity IDs are stored in entry data and that is the binding. No pattern matching, no fuzzy device-registry search, none of the machinery at `helpers.py:119-190` that exists today purely because ESPHome service names had to be guessed. That is the single biggest simplification in this migration.

The emitter and receiver do not have to be the same physical device, and the config flow should not require it. A user with a receiver near the couch and a blaster behind the TV is a legitimate setup.

Both selectors use `EntitySelector(EntitySelectorConfig(domain="infrared", device_class=...))`, which is how `lg_infrared/config_flow.py` does it. `InfraredDeviceClass` is `EMITTER` / `RECEIVER` (verified, `infrared/entity.py:23-27`) and the base classes set `_attr_device_class` automatically (`entity.py:46`, `:106`), so the device-class filter is reliable.

---

## f. Config flow

### New user flow

One step replaces the current `async_step_user` (`config_flow.py:301-382`).

```
async_step_user
  guard: infrared domain loaded, else abort "infrared_not_loaded"
  guard: async_get_emitters(hass) non-empty, else abort "no_emitters"
  form:
    emitter (required)  EntitySelector(domain=infrared, device_class=emitter)
    receiver (optional) EntitySelector(domain=infrared, device_class=receiver)
    name (optional)     defaults to the emitter's friendly name
  unique_id = f"{emitter_entity_id}|{receiver_entity_id or ''}"
```

Receiver optional is deliberate. A send-only setup, whether a Broadlink emitter or a blaster with no receiver wired, is a valid library to own. Without a receiver, the Learn button is unavailable and presets are the only way to add codes, which is exactly the case decision 4 exists to serve.

The unique ID changes from a normalized MAC to the entity pair. That is a downgrade in stability, because a user who renames their ESPHome device changes its entity IDs. The mitigation is to also store the entity registry entry IDs, which survive renames, and resolve through them at setup. HA's own `er.async_validate_entity_id` accepts either form, which is why `async_subscribe_receiver` takes `entity_id_or_uuid`.

### Reconfigure

`async_step_reconfigure` (`config_flow.py:384-466`) keeps its shape and loses all the MAC-identity guarding at `:419-427`. Rebinding to a different emitter or receiver is now an ordinary, safe operation, because the code library is not tied to hardware identity any more. Just re-show the same form pre-filled and update the entry.

### Options flow

The existing `save_code`, `manage_codes` and `confirm_delete` steps (`config_flow.py:501-670`) survive unchanged except for the carrier placeholder at `:579`. The menu at `:496-499` gains `add_preset`, and the dead `settings` step (`:672-677`, currently aborting with `not_implemented`) is either implemented as emitter/receiver rebinding or removed.

### Migration for existing entries

`ConfigFlow.VERSION` goes 1 to 2 (`config_flow.py:38`), and `async_migrate_entry` is added to `__init__.py`.

The migration cannot be fully automatic, and this needs to be said clearly rather than papered over. A v1 entry knows an ESPHome device name, a MAC, a learning switch entity ID and a service name. It does not know an `infrared` entity ID, because those entities only exist after the user adds an `ir_rf_proxy` block to their firmware YAML and reflashes. No amount of registry searching can conjure them.

So the migration is best-effort with a guaranteed fallback:

1. Migrate the storage file to schema v2 regardless. The code library is the valuable thing and it survives no matter what.
2. Try to auto-bind. Look up the device in the registry by the stored MAC (`CONF_MAC_ADDRESS`), enumerate its entities, and if exactly one `infrared` emitter and at most one `infrared` receiver are attached, bind them and finish silently. The user reflashed before upgrading and everything just works.
3. If that fails, mark the entry migrated to version 2 with the emitter and receiver unset, and start a reauth flow (`async_start_reauth`). HA surfaces that as a "reconfigure needed" card. The reauth step is the same emitter/receiver picker as `async_step_user`.
4. Until the user completes it, `async_setup_entry` raises `ConfigEntryNotReady` with a message naming what is missing. Entities do not load, the storage file is untouched, and nothing is lost.

Path 3 is not a failure case, it is the expected path for most users, and the release notes and the repair message should say so plainly: upgrade the firmware, then pick your emitter.

Firmware side, this is what the user adds to `factory_flash.yaml`. It is purely additive and coexists with the existing `remote_receiver` / `remote_transmitter` blocks, which keep their IDs `ir_rx` (`factory_flash.yaml:197`) and `ir_tx` (`:283`):

```yaml
infrared:
  - platform: ir_rf_proxy
    name: IR Transmitter
    remote_transmitter_id: ir_tx
  - platform: ir_rf_proxy
    name: IR Receiver
    receiver_frequency: 38kHz
    remote_receiver_id: ir_rx
```

The existing transmitter already sets `carrier_duty_percent: 50%` (`factory_flash.yaml:285`), which satisfies the `ir_rf_proxy` final-validation rule that rejects 0 or 100 percent. Bump `esphome.project.version` from `0.5.0` (`factory_flash.yaml:14`) at the same time.

Once the firmware carries `ir_rf_proxy`, HA's ESPHome integration auto-creates the two `infrared` entities with no user action beyond the reflash (verified, `esphome/infrared.py:112-137` at 2026.9.0, which picks receiver or emitter by capability bit).

---

## g. Deletion list

This is the subtraction half. 24 discrete items, roughly 1,000 lines removed outright across five modules, plus about 90 lines of transport code rewritten in place.

### learning.py, roughly 385 lines

| # | What | Lines |
|---|---|---|
| 1 | Capture-marker and replay constants | `42-61` |
| 2 | Dangling-MAC regex and its comment | `63-67` |
| 3 | `_pending_replay_tasks` field | `130-133` |
| 4 | Learning-switch turn-on block | `231-243` |
| 5 | Bus subscription to `EVENT_LEARNED` | `246-248` |
| 6 | Marker resolution and subscription in start | `250-269` |
| 7 | `_async_turn_off_learning_mode` plus 5 call sites | `313-323` |
| 8 | `_resolve_text_sensor_entity_id` | `325-385` |
| 9 | `_async_handle_capture_marker_change` | `387-427` |
| 10 | `_async_wait_then_request_replay` | `429-447` |
| 11 | `_async_request_replay` | `449-475` |
| 12 | `_async_handle_learned_event`, the entire handler | `477-593` |
| 13 | `pulses_json` parse and carrier coercion/validation | `616-650` |
| 14 | `_cancel_pending_replay_tasks` and its teardown call | `697-704`, `298` |
| 15 | Learning-switch turn-off in `async_cleanup` | `888-904` |

The `_capture_finalized` guard (`121-126`, `611-614`, `674`, `754`, `807`) stays. It was introduced for the event-versus-replay race, which is gone, but it also guards the capture-versus-timeout and capture-versus-cancel races at `learning.py:754` and `:807`, which are not.

### helpers.py, roughly 143 of 209 lines

| # | What | Lines |
|---|---|---|
| 16 | `AmbiguousEsphomeServiceError` | `25-31` |
| 17 | `async_flag_send_service_missing` / `async_clear_send_service_missing` and their 8 call sites | `34-59` |
| 18 | `claimed_service_names` | `96-116` |
| 19 | `discover_esphome_service` | `119-190` |
| 20 | `get_esphome_service` | `193-209` |

Only `async_remove_code_entities` (`62-93`) survives. The module is worth renaming or folding into `__init__.py`.

### __init__.py, roughly 221 lines

| # | What | Lines |
|---|---|---|
| 21 | `_lookup_mac_from_esphome_device` and `_async_flag_ambiguous_backfill` | `58-182` |
| 22 | MAC back-fill and ESPHome service discovery in setup | `286-346` |
| 23 | Stuck learning-switch reset background task | `417-453` |

`_async_migrate_controls_device` (`185-228`) and `_async_remove_orphaned_entities` (`231-277`) both stay. They are registry hygiene, unrelated to transport, and `docs/SESSION_KNOWLEDGE.md` records that the Controls-device migration is still being watched in the v1.2 beta.

### config_flow.py, roughly 239 lines

| # | What | Lines |
|---|---|---|
| 24 | `_get_available_openirblaster_devices`, `_find_selected_device_info`, `_resolve_learning_switch`, `_resolve_esphome_service` | `40-281` |

### Constants, strings and config data

- `const.py:6-18`: `CONF_LEARNING_SWITCH_ENTITY_ID`, `CONF_ESPHOME_DEVICE_NAME`, `CONF_ESPHOME_SERVICE_NAME`, `DEFAULT_LEARNING_SWITCH_PATTERN`, `DEFAULT_SERVICE_NAME_PATTERN`, `EVENT_LEARNED`.
- `const.py:47-54`: `ATTR_DEVICE_ID`, `ATTR_MAC_ADDRESS`, `ATTR_PULSES_JSON`, `ATTR_RSSI`, `ATTR_TIMESTAMP`. `ATTR_RSSI` is worth a second look, since `InfraredReceivedSignal` has no signal-strength field, so the `rssi` attribute on the `code_learned` event (`event.py:116-117`) and on `LearnedCode` (`learning.py:80`) has no source under v2 and should be dropped.
- `manifest.json:6`: `"dependencies": ["esphome"]` becomes `["infrared"]`. Do not add `infrared-protocols` to `requirements` (`manifest.json:11`), it arrives with the dependency and a competing pin against a library on its tenth major version is a real hazard.
- `strings.json`: the `service_not_found` config error, the `dangling_mac` and `esphome_service_missing` and `ambiguous_mac_backfill` repair issues, and the `mac_unavailable` / `wrong_device` config aborts.
- Entry data: `CONF_ESPHOME_DEVICE_NAME`, `CONF_ESPHOME_SERVICE_NAME`, `CONF_LEARNING_SWITCH_ENTITY_ID`, `CONF_MAC_ADDRESS`, `CONF_DEVICE_ID` all drop out of `entry.data` after migration. `diagnostics.py:25-34` redacts four of them and needs updating.
- `data.py:24`: `esphome_service_name` field, replaced by `emitter_entity_id` and `receiver_entity_id`.

---

## h. Test plan

### What exists

137 test functions in 12 files, 4,192 lines. ESPHome coupling by file:

| File | Tests | ESPHome references | Fate |
|---|---|---|---|
| `test_learning.py` | 41 | 37 | Largest rewrite. Every capture test changes its input shape |
| `test_services.py` | 20 | 16 | Send-path assertions rewritten, learn tests follow `test_learning` |
| `test_init.py` | 18 | 42 | Most rewritten. MAC back-fill and discovery tests delete outright |
| `test_config_flow.py` | 14 | 28 | Almost entirely rewritten |
| `test_dynamic_entities.py` | 10 | 6 | Fixture changes only |
| `test_storage.py` | 9 | 0 | Survives, gains migration tests |
| `test_button.py` | 8 | 14 | Send assertions rewritten |
| `test_text.py` | 6 | 0 | Survives |
| `test_event.py` | 5 | 0 | Survives, minor attribute changes |
| `test_sensor.py` | 3 | 0 | Survives |
| `test_translations.py` | 2 | 0 | Survives, catches missing new keys automatically |
| `test_diagnostics.py` | 1 | 0 | Survives, assertions updated |

Roughly 85 of 137 tests need real work. Call it 60 rewritten and 25 deleted, with about 45 new ones added.

### Faking the infrared domain

`conftest.py:29-77` currently fakes the entire ESPHome integration by patching `loader.async_get_integration` to return a `MagicMock(spec=Integration)`. That will not work for `infrared`, because the integration's code calls real functions in it. A different approach is needed.

`infrared` is a real core integration with no config entry and no requirements of its own beyond the library, so the cleanest route is to set it up for real:

```python
@pytest.fixture
async def infrared_domain(hass):
    assert await async_setup_component(hass, "infrared", {})
```

That gives a real `EntityComponent` under `hass.data[DATA_COMPONENT]`, which means `async_get_emitters`, `async_get_receivers`, `async_send_command` and `async_subscribe_receiver` all behave exactly as they do in production. It requires `infrared_protocols` in the test environment, which means adding it to `requirements_dev.txt` explicitly (it is a HA requirement, not installed by `pip install homeassistant`, which is why `import infrared_protocols` fails in the current `.venv` today).

Then register fake platform entities:

```python
class FakeEmitter(InfraredEmitterEntity):
    _attr_unique_id = "fake_emitter"
    def __init__(self):
        self.sent: list[InfraredCommand] = []
    async def async_send_command(self, command):
        self.sent.append(command)

class FakeReceiver(InfraredReceiverEntity):
    _attr_unique_id = "fake_receiver"
    def emit(self, timings, modulation=None):
        self._handle_received_signal(InfraredReceivedSignal(timings, modulation))
```

`_handle_received_signal` is `@final` but not private (verified, `infrared/entity.py:145-160`), so calling it from a test fixture is the intended platform contract, which is exactly what `esphome/infrared.py:109` does.

That single pair of fixtures replaces the whole `setup_esphome_integration` fixture, the bus-event fixtures, and every `hass.services.async_register("esphome", ...)` call in `conftest.py:91-93` and `:112-114`.

### Faking infrared_protocols

Do not fake it. It is pure Python with zero runtime dependencies and no I/O, and faking it would test the fake rather than the resolution logic.

The one thing worth faking is the failure path: monkeypatch `presets.resolve` to raise `PresetUnavailable` and assert the repair issue and the surviving entity. Enumeration tests should assert shape (at least one brand, every returned member callable with no arguments) rather than exact counts, so a library bump does not break the suite.

### New tests needed

Storage migration, roughly 10:
- v1 file with codes migrates to v2, every code gains `source: "learned"`, `carrier_hz` preserved verbatim.
- Empty v1 file, v1 file with no `codes` key, v1 file with a `last_learned` block.
- Migration is idempotent on a v2 file.
- v3 file is rejected, not silently loaded.
- Hand-edited v1 file per `docs/storage-format.md` survives.

Capture path, roughly 12:
- Subscription created on arm, released on capture, timeout, cancel and unload.
- `modulation=None` stores `carrier_hz: None`; `modulation=36000` stores 36000.
- Signal arriving while IDLE is ignored.
- Oversized timings array (> 2000) rejects with the existing error.
- Receiver going unavailable mid-window ends the session with a clear reason.
- Receiver entity missing at arm time raises `HomeAssistantError`.

Locking, roughly 5:
- Two entries on the same receiver: the second arm is rejected and the first is unaffected.
- Two entries on different receivers arm concurrently.
- Receiver claim is released on every terminal path.
- Claim survives a failed arm without leaking.

Send path, roughly 8:
- Learned code sends a `RawCommand` with the stored timings verbatim and the stored modulation.
- `carrier_hz: None` sends at 38000.
- Preset code resolves and sends the library's command.
- Unresolvable preset raises a repair and leaves the button in place.
- Emitter unavailable makes the button unavailable.

Config flow, roughly 10:
- No infrared domain, no emitters, emitter only, emitter plus receiver, duplicate pair.
- Migration v1 to v2 with a resolvable device, migration with an unresolvable device starting reauth, reauth completing.

Presets, roughly 8:
- Enumeration returns brands, brands return devices, devices return commands.
- `EdifierModel` and `EdifierCommandSet` are filtered out.
- Adding a preset stores `source: "preset"` with no pulses and dispatches `SIGNAL_CODE_ADDED`.
- Duplicate name rejected.

### CI

`docs/SESSION_KNOWLEDGE.md` records two CI-specific traps that this migration walks straight into. Both need attention in Phase 7:

- CI runs Python 3.12 with pinned requirements. That has to become 3.14, because `infrared-protocols` will not install otherwise.
- CI's `pytest-homeassistant-custom-component` fails on lingering timers and tasks at teardown where the local venv does not. The receiver subscription is a new lifetime object with the same failure shape as the `async_call_later` leak that already bit this project, so every test that arms a session must tear it down through an async-generator fixture.

`requirements_dev.txt` needs `homeassistant>=2026.9.0` (currently `>=2024.1.0`) and an explicit `infrared-protocols`. `hacs.json` needs `"homeassistant": "2026.9.0"`.

---

## i. Risk register

### 1. ir_rf_proxy is experimental, no breaking-change policy

The ESPHome docs carry an explicit banner: the API may change at any time without following the normal breaking changes policy. The whole v2 transport rests on it, on both ends, since HA's ESPHome infrared platform speaks to it over the native API.

Likelihood moderate, impact high. A breaking change means a firmware reflash for every user, and possibly a coordinated HA upgrade.

What reduces it: the storage layer is untouched by any such break, so a bad ESPHome release costs a reflash and not a code library. Keep the existing `remote_receiver` / `remote_transmitter` blocks in `factory_flash.yaml` rather than replacing them, so the old path physically still exists on the device if it is ever needed. Watch `esphome/esphome` releases during the v2.0 beta. Do not pin the firmware to exactly 2026.1.0; the component was broken in HA entity setup as late as 2026-02-24 (esphome issue 14218) and gained `receiver_frequency` in March and an `on_control` trigger in May. Recommend 2026.5.0 or newer in the docs.

### 2. Python 3.14 floor versus a 3.12 project target

`infrared-protocols` declares `requires-python = ">=3.14"`, verified from PyPI metadata. CLAUDE.md says 3.12+, `hacs.json` says HA 2024.12.0, `requirements_dev.txt` says `homeassistant>=2024.1.0`, and CI runs 3.12.

The real minimum for a v2.0 user: Home Assistant 2026.9.0, which implies Python 3.14, plus ESPHome 2026.1.0 on the device (2026.5.0 recommended).

Impact is mostly on Jay's own CI, since HA 2026.6+ already forces 3.14 on users. The user-facing cost is the honest one: a v1.2.3 user on HA 2024.12 cannot take this upgrade without first upgrading HA across nearly two years of releases. That is what "clean cut" means and it should be stated in the release notes rather than discovered.

### 3. The codeset and library API churn between versions

Ten major versions in five months, and I verified two concrete breaks between the version HA 2026.4 pins (1.1.0) and the one dev pins (10.1.0): `get_raw_timings()` changed return type, and `make_command` became `Enum.to_command`. Core owns the pin, so pinning is not available.

Likelihood high, impact medium. It hits the presets feature specifically, and learned codes are unaffected because `RawCommand` only depends on the `Command` ABC, which has been stable in shape.

What reduces it: keep the library surface behind `presets.py` so a break is one module to fix. Store the symbol path rather than resolved timings, so a codeset change is picked up rather than frozen. Treat `PresetUnavailable` as a first-class outcome with a repair issue, never an exception that kills an entity. Assert shape rather than exact counts in tests. Record `library_version` at add time so support conversations have the evidence.

### 4. Users on ESPHome firmware older than 2026.1.0

Anyone who flashed `factory_flash.yaml` at its current `project.version: 0.5.0` has no `ir_rf_proxy` block and therefore no `infrared` entities. For them, v2.0 does nothing until they reflash.

Likelihood: certain, this is every existing user. Impact medium, because the recovery is a documented reflash and the code library survives untouched.

What reduces it: the migration path in section f, specifically that storage migrates regardless and the entry lands in reauth rather than failing. Ship the firmware change and the integration change in the same release. Lead the release notes with "reflash first, then upgrade". Consider shipping v1.2.4 first with a deprecation notice pointing at the firmware change, so users can reflash ahead of the cut and land on path 2 rather than path 3.

### 5. Carrier frequency is lost on every new capture

`esphome/infrared.py:109` at 2026.9.0 constructs `InfraredReceivedSignal(timings=event.timings)` with no `modulation`. Verified. ESPHome's `receiver_frequency` config option is documented in its own source as metadata only with no hardware effect, and it is not plumbed through.

This is decision 3 and it is settled. Recording it as a risk anyway because it has a user-visible consequence worth naming in the release notes: a device that genuinely needs 36 kHz or 40 kHz, learned under v2, will be stored at None and sent at 38 kHz and may not work. The `send_code` service already accepts a `carrier_hz` override (`services.yaml:47-54`), and `storage.async_update_code` already accepts one (`storage.py:166`), so the recovery exists. It is just not discoverable. Consider surfacing carrier as an editable field in the options flow so a user with a 36 kHz device can fix it once and be done.

### 6. Pronto round-trip fidelity, if that path is ever taken

Measured drift up to 45µs per interval and a modulation that reads back as 38029 rather than 38000. Mitigated entirely by using `RawCommand`. Listed so the decision is not silently revisited later by someone who notices `ProntoCommand.from_raw_timings` and thinks it is the obvious choice.

### 7. Preset enumeration depends on unsupported package layout

`importlib.resources` traversal of another package's directory structure is not an API contract. If the library ever ships as a zip, adds `__init__.py` files, or restructures `codes/`, enumeration breaks.

Likelihood moderate, impact low, because it degrades to "no presets available" rather than breaking anything. Catch the traversal failure, cache the result, log once, and let learned codes carry on.

### 8. No established test pattern for a custom integration consuming infrared

None of the eight core consumer integrations is a custom component, and `pytest-homeassistant-custom-component` ships no infrared fixtures. The approach in section h (set up the real domain, register fake entities) is sound but unproven for this project.

Likelihood moderate, impact low. It is a day of fixture work at worst, and it should be de-risked early rather than left to Phase 7. Build the fake emitter and receiver in Phase 1 alongside the send path, before the capture rework depends on them.

---

## j. Implementation sequence

Effort is developer-days for one person who knows this codebase. Each phase ends green: tests pass, `ruff check .` clean, HA loads the integration.

### Phase 0: floors and dependency, 0.5 day

Bump `manifest.json` dependencies to `["infrared"]` and version to `2.0.0-beta.1`. `hacs.json` to `"homeassistant": "2026.9.0"`. `requirements_dev.txt` to `homeassistant>=2026.9.0` plus an explicit `infrared-protocols`. CI workflow to Python 3.14. Update CLAUDE.md's stated target.

Gate: the existing suite runs on 3.14 against HA 2026.9, with pre-existing failures catalogued rather than fixed.

Risk if skipped or trimmed: none, this is unavoidable.

### Phase 1: the send path, 1.5 days

New `commands.py` with `RawCommand`. Swap the three ESPHome call sites (`button.py:406-434`, `button.py:481-511`, `services.py:266-285`) to `infrared.async_send_command`. Add `emitter_entity_id` to `data.py` and read it from entry data with a hardcoded test value for now. Build the `FakeEmitter` fixture.

Gate: a stored code sends through a fake emitter with byte-identical timings.

Trimmable: no. Everything downstream needs the fake-entity fixtures this phase builds.

### Phase 2: the capture path, 3 days

Rewrite `learning.py`. Delete items 1 through 15 in the deletion list. Add the receiver subscription lifecycle, receiver availability tracking, and the per-receiver claim registry. Build the `FakeReceiver` fixture. Rewrite the capture half of `test_learning.py`.

Gate: arm, emit from the fake receiver, capture commits, subscription released. Timeout, cancel and unload each release cleanly with no lingering timers under CI's stricter teardown.

Trimmable: the per-receiver claim registry could ship in a later beta if Jay accepts that two entries on one receiver misbehave. I would not, because it is a silent data-corruption bug (two codes saved from one press) rather than a visible one.

### Phase 3: storage migration, 1 day

`STORAGE_VERSION` to 2, write `_async_migrate_func`, add `source` and `preset` to the schema, thread nullable `carrier_hz` through the read sites listed in section c. Update `docs/storage-format.md`.

Gate: a real v1 storage file from a running install migrates, sends correctly at its original carrier, and round-trips through save and reload.

Trimmable: no.

### Phase 4: config flow and entry migration, 2 days

Rewrite `async_step_user` and `async_step_reconfigure`. Delete item 24. Add `async_migrate_entry` with the three-path logic from section f, plus the reauth step. Update `strings.json` and `translations/en.json`. Rewrite `test_config_flow.py`.

Gate: a v1 entry with a resolvable device auto-migrates; one without lands in reauth without losing storage; reauth completes and entities load.

Trimmable: the auto-bind attempt (path 2) could be dropped, sending every user to reauth. It is maybe two hours of work and it is the difference between a silent upgrade and a support thread, so keep it.

### Phase 5: entity model, 1 day

Availability tracking on the send buttons (emitter) and the Learn button (receiver). Drop `rssi` from `LearnedCode` and the `code_learned` event. Add `source` to `code_saved`. Update `diagnostics.py`.

Gate: an unavailable emitter greys out the code buttons; an unavailable receiver greys out Learn.

Trimmable: yes, partly. Availability tracking is real polish rather than correctness, and it could ship in 2.1. The `rssi` removal cannot wait, because there is no source for it.

### Phase 6: presets, 3 days

New `presets.py` with enumeration and resolution. Three options-flow steps, the `add_preset` service, `PresetUnavailable` and its repair issue, preset dispatch in `CodeButton`. Strings for all of it. New tests.

Gate: pick LG, TV, POWER, name it, get a working button that transmits.

Trimmable: this is the obvious candidate to defer to 2.1, and it is the only phase that is genuinely optional. It is also the phase most exposed to library churn, so shipping it separately from the transport migration has a real argument behind it. Deferring it does not change any schema decision, since the `source` field and nullable `pulses` land in Phase 3 either way.

### Phase 7: test suite and CI, 2.5 days

Finish the rewrite of `test_init.py`, `test_services.py`, `test_button.py`, `test_dynamic_entities.py`. Replace the `setup_esphome_integration` fixture in `conftest.py`. Chase the lingering-timer failures that CI will find and the local venv will not.

Gate: full suite green on CI at Python 3.14, coverage no lower than today.

Trimmable: no. `docs/SESSION_KNOWLEDGE.md` already records that local green does not mean CI green for this project.

### Phase 8: firmware, docs, release, 1 day

Add the `infrared:` block to `factory_flash.yaml`, bump `project.version`. Rewrite `docs/firmware-and-esphome.md` and `docs/home-assistant-integration.md`. Update `README.md` and `docs/troubleshooting.md`. Add a v2.0 upgrade guide covering reflash-then-upgrade. Update `docs/SESSION_KNOWLEDGE.md` with what this migration taught. Version bump per the release rules (`docs/SESSION_KNOWLEDGE.md` records that every master push must bump `manifest.json`).

Gate: a clean install on real hardware, and a v1.2.3 upgrade on real hardware, both working.

### Totals

| Scope | Phases | Days |
|---|---|---|
| Full plan | 0 through 8 | 15.5 |
| Without presets | 0 through 5, 7, 8 | 12.5 |
| Without presets and without availability polish | 0 through 4, 7, 8 | 11.5 |

Phases 0 through 4 are the irreducible core. Below that the integration does not work.
