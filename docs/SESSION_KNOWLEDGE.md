# Session Knowledge

Accumulated non-obvious learnings about this project. Read before making architectural decisions; update when something important, non-obvious, or counter-intuitive is discovered. Include dates so staleness can be assessed.

## Architecture decisions

### Two-device "Controls" layout vs unified device with entity categories (2026-06-12)

- The original two-device layout (main device + virtual "Controls" device, added 2026-01-13 in `df0bd0f`) existed to quarantine the per-code DELETE button entities that shipped at the time (one-click delete, disabled by default for safety).
- Those delete buttons were removed on 2026-01-20 (`5bcfc3a`) once the two-step options-flow delete (select, then confirm) shipped. After that, the Controls device held only benign entities.
- **A unified device with entity categories was attempted once before and abandoned due to issues, but the attempt was never committed and the specific issues are not remembered.** v1.2.0 (beta) re-attempts it with an idempotent migration that re-points entity registry entries before deleting the Controls device. Watch the beta for whatever broke last time: candidate failure modes are orphaned entities, lost customizations, duplicate devices, or surprise dashboard/voice-assistant exposure changes (categories intentionally remove entities from auto-dashboards and default Assist exposure).
- Downgrading v1.2.0 -> v1.1.0 self-heals: v1.1.0 recreates the Controls device at setup and entities re-attach (unique_ids unchanged in both directions).

### Deletion must stay a two-step process (2026-06-12)

Deliberate product decision: deleting a code always requires select-then-confirm (options flow) or an explicit service call with the exact code id. Never reintroduce one-click delete entities.

## Release and CI mechanics

### Every master push must bump the version (2026-06-12)

- The Release workflow auto-tags and publishes a GitHub release from `manifest.json` on every master push where the tag does not already exist.
- The CI workflow's Version Check job fails any master push whose manifest version equals the latest release tag. Consequence: docs-only or fix-only commits cannot be pushed alone; bundle them with a version bump.
- Betas: the workflow always publishes a full release; flip it afterwards with `gh release edit vX.Y.Z --prerelease`. Promote with `--prerelease=false`.

### CI test environment is stricter than the local venv (2026-06-12)

- CI runs Python 3.12 with pinned requirements; the local `.venv` is Python 3.14 with a newer HA. CI's pytest-homeassistant plugin fails on lingering timers/tasks at teardown that the local environment silently allows. Local green does not guarantee CI green.
- Two incidents: (1) tests arming a learning session without cleanup leaked the `async_call_later` timeout timer (fixed with async-generator fixtures that `await session.async_cleanup()`); (2) push-based entities without `_attr_should_poll = False` made EntityPlatform schedule a poll interval timer (HA's `EventEntity`, `SensorEntity`, and `TextEntity` bases do NOT disable polling; `ButtonEntity` does).

## Home Assistant compatibility

### Options flow `config_entry` property needs HA 2024.12 (2026-06-12)

The inherited `OptionsFlow.config_entry` property only exists from HA 2024.12.0 (the 2024.11 dev blog announced it, but the property itself landed in 2024.12). v1.1.0 shipped declaring 2024.11 support and its options flow crashes there. The floor is now 2024.12.

### ESPHome service discovery must not pattern-match across entries (2026-06-12)

With two blasters where one is offline at boot, a bare `*_send_ir_raw` pattern fallback binds the offline entry to the other device's service and IR transmits from the wrong device. Discovery must exclude service names claimed by other entries and refuse ambiguous matches (raise ConfigEntryNotReady instead).
