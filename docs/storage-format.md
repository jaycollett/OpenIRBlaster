# Storage Format & Manual Editing

> **Use case:** the integration normally writes this file for you. Edit it by hand only as a workaround when you can capture an IR signal in ESPHome logs but the integration's learning session isn't picking it up (see issue [#9](https://github.com/jaycollett/OpenIRBlaster/issues/9)).

## File Location

The integration stores all learned codes in Home Assistant's storage area:

```
<HA config>/.storage/openirblaster_<entry_id>
```

The file name has no extension. `<entry_id>` is the config entry ID, and there is one storage file per OpenIRBlaster device added to Home Assistant, so the quickest way to find yours is to list them:

```bash
ls <HA config>/.storage/openirblaster_*
```

Each file carries its own ID and device name under `data.device`, which is how you tell two blasters apart. To look an ID up first instead, `.storage/core.config_entries` lists every config entry with its integration and title, and the **Config entry** dropdown on any OpenIRBlaster action in **Developer Tools -> Actions** fills the ID in for you once you switch that action to YAML mode.

## When You Remove the Integration

From version 1.3.2, deleting an OpenIRBlaster entry in **Settings -> Devices & Services** leaves its storage file where it is. Home Assistant removes the device and its entities, and the file keeps every code, including the carrier frequency measured when each one was learned. The command-line exporter, `tools/openirblaster_to_wig.py`, can still convert it to HAIR's format after the integration is gone.

Version 1.3.1 and earlier deleted the file along with the entry. On one of those versions, export or pluck your codes first, or update before you remove anything.

Adding the same blaster again creates a new config entry with a new ID, and so a new, empty storage file. The old file stays alongside it and the integration does not read it. To bring the codes back into the new entry, copy them across with the [Safe Manual-Edit Procedure](#safe-manual-edit-procedure). Once the codes are somewhere you trust, you can delete the old file by hand.

## On-Disk Format

The file follows Home Assistant's standard storage envelope. Your code data lives inside `data`:

```json
{
  "version": 1,
  "minor_version": 1,
  "key": "openirblaster_01HZABCDEFGHIJK",
  "data": {
    "version": 1,
    "device": {
      "config_entry_id": "01HZABCDEFGHIJK",
      "name": "OpenIRBlaster",
      "device_id": "openirblaster-2ca965",
      "last_learned": {
        "name": "TV Power",
        "timestamp": "2026-04-01T12:34:56+00:00",
        "pulse_count": 8
      }
    },
    "codes": [
      {
        "id": "tv_power",
        "name": "TV Power",
        "carrier_hz": 38000,
        "pulses": [9000, -4500, 560, -560, 560, -1690, 560, -560],
        "created_at": "2026-04-01T12:34:56+00:00",
        "updated_at": "2026-04-01T12:34:56+00:00",
        "tags": [],
        "notes": ""
      }
    ]
  }
}
```

### Schema versioning

The top-level `version` / `minor_version` pair is Home Assistant's storage
envelope versioning, managed by the integration:

- `version` (major) changes only for breaking schema rewrites.
- `minor_version` changes for additive schema extensions.

Both are defined in `const.py` (`STORAGE_VERSION` / `STORAGE_MINOR_VERSION`,
currently `1` / `1`). On load, `storage.OpenIRBlasterStore._async_migrate_func`
migrates older data forward; data written by a NEWER schema than the
installed integration knows is rejected rather than silently loaded. When
editing by hand, leave both version fields exactly as you found them.

### The `device.last_learned` block

`device.last_learned` records the most recently saved code's metadata
(`name`, `timestamp`, `pulse_count`). It backs the three "Last Learned"
diagnostic sensors so their values survive Home Assistant restarts. It is
optional: absent until the first code is saved, and safe to leave untouched
(or omit) when editing by hand. Do not point it at a code that does not
exist; it is display metadata only and is overwritten on the next save.

### Code fields

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `id` | string | yes | Lowercase slug. Must be unique within the file. Used to derive the button entity ID. **Once set, do not rename** - renaming the `id` orphans the button entity in the registry. |
| `name` | string | yes | Human-readable display name shown on the button. Safe to change. |
| `carrier_hz` | int | yes | IR carrier frequency, typically `38000`. |
| `pulses` | array of int | yes | Pulse timings in microseconds. Positive = mark (LED on), negative = space (LED off). Max 2000 elements. |
| `created_at` | ISO 8601 string | yes | UTC timestamp. |
| `updated_at` | ISO 8601 string | yes | UTC timestamp. Update this when you change the entry. |
| `tags` | array of string | yes | May be empty. |
| `notes` | string | yes | May be empty. |

## Getting Pulse Data from ESPHome Logs

When learning mode is armed, the ESPHome firmware logs the captured pulses before firing the event. In the ESPHome dashboard logs you'll see entries like:

```
[remote.raw:028]: Received Raw: 9000, -4500, 560, -560, 560, -1690, 560, -560, ...
```

The comma-separated integers are exactly the array that belongs in `pulses`. Copy them verbatim.

The carrier frequency from the same capture is what goes in `carrier_hz` (typically `38000`).

## Safe Manual-Edit Procedure

> **Important:** Home Assistant caches `.storage` contents in memory. If you edit the file while HA is running, your changes will be **overwritten the next time the integration saves** - for example when a new code is learned, renamed, or deleted. The user in [issue #9](https://github.com/jaycollett/OpenIRBlaster/issues/9) lost two remotes of manual entries this way.

Always follow this sequence:

1. **Stop Home Assistant** (full stop, not just a restart trigger from the UI - use your supervisor / `systemctl stop home-assistant` / container stop, whatever applies to your install).
2. **Back up the file** first: `cp openirblaster_<entry_id> openirblaster_<entry_id>.bak`
3. **Edit** the file with a JSON-aware editor (VS Code, Notepad++ with the JSON plugin, `jq`). Validate the JSON before saving.
4. **Start Home Assistant** again. The integration loads the file on startup and creates a button entity for each code that has a unique `id`.

If a button entity doesn't appear for a code you added, check the Home Assistant logs at startup for parsing errors from `custom_components.openirblaster.storage`.

## Adding a New Code by Hand

Append an object to the `data.codes` array. Minimum viable entry:

```json
{
  "id": "onkyo_power",
  "name": "Onkyo Power",
  "carrier_hz": 38000,
  "pulses": [9000, -4500, 560, -560, 560, -1690, 560, -560],
  "created_at": "2026-05-14T00:00:00+00:00",
  "updated_at": "2026-05-14T00:00:00+00:00",
  "tags": [],
  "notes": "Added manually from ESPHome logs"
}
```

Rules:
- `id` must be unique within `data.codes` and match `[a-z0-9_]+` (lowercase letters, digits, underscores).
- `pulses` must be a non-empty JSON array of integers, length <= 2000.
- The button entity ID derived from this code will be `button.openirblaster_<id>` (`button.openirblaster_onkyo_power` in this example).

## Editing an Existing Code

- **Renaming a button label:** change `name`, update `updated_at`. The entity ID stays the same.
- **Replacing the captured signal:** swap out `pulses` (and `carrier_hz` if needed), update `updated_at`.
- **Deleting a code:** remove its object from the `codes` array, then on next HA start the integration will clean up the orphaned button entity from the entity registry.

Do not edit `id` once a code has been used. If you must change the slug, delete the old entry and add a new one with the new ID.

## Validating Before Restart

A quick sanity check from a shell:

```bash
jq '.data.codes | length' openirblaster_<entry_id>   # number of codes
jq '.data.codes | map(.id)' openirblaster_<entry_id> # list IDs - must be unique
jq -e '.data.codes | map(.pulses | length) | max <= 2000' openirblaster_<entry_id>
```

If any of those error, fix the file before restarting Home Assistant.
