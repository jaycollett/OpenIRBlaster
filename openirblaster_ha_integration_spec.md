# OpenIRBlaster Home Assistant Integration — Technical Specification (v0.1)

**Purpose:** Build a Home Assistant custom integration that **owns the IR code library** (store, name, organize, send), while the ESPHome firmware remains “dumb” (learn + transmit only).  
**Target hardware/firmware:** ESP8266 ESPHome device with IR TX on GPIO14 and IR RX (TSOP38238) on GPIO4.

---

## 1) Goals

### 1.1 Primary goals
- Provide a **Learn → Name → Save → Send** workflow fully inside Home Assistant.
- Store learned codes in Home Assistant persistent storage (`.storage/`), not in firmware.
- Expose each saved IR code as a **Button entity** (press = transmit) and optionally as **Scripts** (optional future).
- Support multiple OpenIRBlaster devices (each device has its own library namespace, or shared if desired).

### 1.2 Non-goals (initial release)
- No protocol-specific decoding/encoding (NEC/Sony/etc.) beyond raw pulses.
- No cloud services or external databases.
- No auto-generation of YAML in user configs.
- No advanced UI for editing raw arrays (provide export/import later).

---

## 2) High-level architecture

### 2.1 Components
1) **ESPHome firmware**
   - Receives IR frames and emits a “learned” notification to HA.
   - Provides an API service to transmit raw IR: `send_ir_raw(carrier_hz, code[])`.
   - Provides a control to enable/disable learning mode.

2) **Home Assistant custom integration** (`custom_components/openirblaster/`)
   - Discovers/configures a specific OpenIRBlaster device (via Config Flow).
   - Listens for learned code notifications from that device.
   - Presents UI to name and save the new code.
   - Stores code library in `.storage/openirblaster_<entry_id>.json`.
   - Exposes entities: Buttons (send), Sensors (last learned), Switch (learning mode passthrough optional).

### 2.2 Data flow
- User enables learning in HA → HA calls ESPHome entity/service to enable learning.
- Device receives IR and notifies HA → integration catches notification.
- Integration prompts user in UI to name/save → user confirms.
- Integration stores to `.storage/…` and creates a new **Button** entity.
- When user presses button → integration calls ESPHome service `send_ir_raw()` with the stored payload.

---

## 3) ESPHome firmware contract (required)

### 3.1 Required entities and services
The firmware must expose:

1) **Switch**: `IR Learning Mode`
   - Turns learning on/off.
   - Integration can turn it on before learning.

2) **Service**: `send_ir_raw`
   - Parameters:
     - `carrier_hz: int`
     - `code: int[]` (raw pulse timings in microseconds, positive/negative as ESPHome expects)
   - Action: transmits via `remote_transmitter.transmit_raw`.

3) **Learned notification mechanism** (choose one)
- **Preferred**: Fire a Home Assistant event via ESPHome `homeassistant.event`.
- **Acceptable**: Update a `text_sensor` with a compact payload + publish a separate event to signal “new code”.
- **Not recommended**: Logging-only output.

### 3.2 Recommended learned event payload
Event type: `openirblaster.learned`

Payload (JSON-like):
- `device_id`: string (ESPHome device name or mac suffix hostname)
- `carrier_hz`: int (typically 38000)
- `pulses`: list[int] (bounded length; HA should accept up to ~2000)
- `timestamp`: ISO string (device or HA time)
- `rssi`: optional int

Example:
```json
{
  "device_id": "openirblaster-64c999",
  "carrier_hz": 38000,
  "pulses": [9000, -4500, 560, -560, ...],
  "timestamp": "2026-01-12T14:30:00-05:00"
}
```

---

## 4) Home Assistant integration functional requirements

### 4.1 Discovery and setup
- Support **Config Flow**:
  - User selects an OpenIRBlaster device from available ESPHome devices OR manually enters entity/service identifiers.
- Store per-entry mapping:
  - learning switch entity_id (default: `switch.<device>_ir_learning_mode`)
  - transmitter service domain/name (default: ESPHome service `esphome.<device>_send_ir_raw` OR via device API)
  - optional: last learned text sensor entity_id (if using sensor-based flow)

### 4.2 Learning workflow
1) User clicks **“Learn code”** (Integration button entity or config entry action)
2) Integration:
   - Turns on `IR Learning Mode` switch
   - Waits for learned event `openirblaster.learned` from that device
   - Turns off learning mode after capture (or after timeout)
3) Integration opens a UI prompt:
   - Code name (required)
   - Optional: device category (TV/Receiver/AC), tags, notes
   - Optional: replace existing code toggle
4) On save:
   - Persist to storage
   - Create/refresh corresponding Button entity

### 4.3 Sending workflow
- Each saved code becomes a **Button entity**:
  - Press → calls ESPHome transmit service with stored `carrier_hz` + `pulses`.
- Provide optional “Send last learned” button for debugging.

### 4.4 Library management
- UI for:
  - List codes
  - Rename
  - Delete
  - Export/Import (phase 2)
- Minimal phase 1: rename/delete via entity services or config entry options.

### 4.5 Concurrency and timeouts
- Only one learning session per device at a time.
- Default learning timeout: 30 seconds.
- If event not received:
  - Turn off learning switch
  - Show persistent notification with failure reason

---

## 5) Data model and storage

### 5.1 Storage location
- `homeassistant/.storage/openirblaster_<config_entry_id>.json`

### 5.2 Storage schema (v1)
```json
{
  "version": 1,
  "device": {
    "config_entry_id": "<entry_id>",
    "name": "OpenIRBlaster",
    "device_id": "openirblaster-64c999"
  },
  "codes": [
    {
      "id": "tv_power",
      "name": "TV Power",
      "carrier_hz": 38000,
      "pulses": [9000, -4500, 560, -560],
      "created_at": "2026-01-12T14:35:00-05:00",
      "updated_at": "2026-01-12T14:35:00-05:00",
      "tags": ["tv"],
      "notes": ""
    }
  ]
}
```

### 5.3 ID rules
- `id` must be stable slug:
  - lowercase, alnum + underscore
  - unique per device entry
- If user enters a name that collides:
  - append `_2`, `_3`, etc.

---

## 6) Entity model

### 6.1 Platforms
- `button`:
  - `button.openirblaster_<entry>_learn` (starts learning session)
  - `button.openirblaster_<entry>_send_last` (optional)
  - `button.openirblaster_<entry>_<code_id>` (one per stored code)

- `sensor` or `text_sensor` equivalent:
  - `sensor.openirblaster_<entry>_last_learned_name` (string)
  - `sensor.openirblaster_<entry>_last_learned_at` (datetime)
  - `sensor.openirblaster_<entry>_last_learned_len` (int)

- `switch` (optional passthrough):
  - Mirror the ESPHome learning mode switch (or just control it internally)

### 6.2 Device registry and entity registry
- Register a HA Device per config entry:
  - manufacturer: `OpenIRBlaster`
  - model: `ESP8266 IR Blaster`
  - sw_version: from config entry or ESPHome device info if available
- Each code button entity belongs to that device.

---

## 7) Services (integration-level)

### 7.1 `openirblaster.learn_start`
- Parameters:
  - `config_entry_id` (or `device_id`)
  - `timeout` optional
- Behavior: start learning session and trigger UI prompt when received

### 7.2 `openirblaster.send_code`
- Parameters:
  - `code_id`
  - optional override `carrier_hz`, `pulses` (for testing)
- Behavior: send via ESPHome service

### 7.3 `openirblaster.delete_code`, `openirblaster.rename_code` (optional)
- Manage stored codes

---

## 8) UI / UX

### 8.1 Config Flow
Step 1: Select discovery method
- Auto-discover ESPHome devices (by device registry entries + integrations)
- OR manual entry of:
  - learning switch entity_id
  - send service entity/service id

Step 2: Validate by calling a lightweight service (optional)

### 8.2 Learn dialog
Use **frontend dialog** triggered via:
- `config_entry` “options flow” action (phase 1) OR
- A minimal Lovelace/Blueprint (phase 1) OR
- A custom panel (phase 2)

**Spec requirement:** The integration must provide a way to input a name without editing YAML.

Pragmatic phase-1 approach:
- Fire a persistent notification with an actionable link is not standard.
- Instead implement an **Options Flow** for “Save pending learned code”:
  - When code received, store it as `pending_code` in memory and set a flag.
  - User goes to the integration’s options and sees the pending code, names it, saves.
  - Provide a “Learn” button entity that sets “learning active” and instructs user to open options to save when learned.

Phase-2 (better UX):
- Add a small frontend component to prompt immediately.

---

## 9) Event handling details

### 9.1 Event subscription
- Subscribe to HA event bus for `openirblaster.learned`.
- Filter:
  - event.data.device_id matches config entry device_id/hostname
  - optionally match MAC

### 9.2 Session state machine
Per device entry:
- `IDLE`
- `ARMED` (learning switch ON, waiting for event)
- `RECEIVED` (pending code captured, learning switch OFF)
- `SAVED` / `CANCELLED` / `TIMEOUT`

---

## 10) Error handling
- If transmit service call fails:
  - Log error and show `persistent_notification.create`
- If learn switch entity missing/unavailable:
  - Show repair issue (`issue_registry`) if possible
- If learned payload too large:
  - Reject with message and instruct to reduce pulses length or adjust firmware truncation.

---

## 11) Security considerations
- Do not store secrets.
- Validate payload types and bounds.
- Optionally enable ESPHome API encryption at firmware level (future).

---

## 12) Implementation plan (files and modules)

### 12.1 File layout
```
custom_components/openirblaster/
  __init__.py
  manifest.json
  const.py
  config_flow.py
  coordinator.py
  storage.py
  learning.py
  button.py
  sensor.py
  services.py
  translations/en.json
```

### 12.2 Key modules
- `storage.py`:
  - load/save JSON storage
  - schema migrations
- `learning.py`:
  - session state machine
  - event subscription + filtering
- `services.py`:
  - register integration services
  - implement send via `hass.services.async_call(...)`
- `button.py`:
  - entity for learn and per-code send buttons
- `coordinator.py`:
  - DataUpdateCoordinator for shared state (optional)

---

## 13) Testing requirements
- Unit tests with `pytest-homeassistant-custom-component`:
  - storage read/write
  - event handling + state machine
  - service calls for transmit invoked with correct payload
  - code id slugging + collision resolution
- Integration test:
  - simulate event bus learned event and verify entity creation.

---

## 14) Open questions / decisions (make explicit in code)
- **Learn UI**: phase-1 options flow vs immediate dialog frontend.
- **Per-device vs shared library**: start per-device.
- **Payload normalization**: keep raw pulses as int list; optionally compress later.

---

## 15) Acceptance criteria (v0.1)
- User can add integration, select an OpenIRBlaster device mapping.
- User can press “Learn” and successfully capture an IR frame (event received).
- User can name and save the code; it persists across HA restarts.
- A new Button entity appears for the saved code; pressing it transmits via ESPHome.
- No YAML editing required for normal operation after integration install.

---

## Appendix A: Firmware recommendations for compatibility
- Avoid `dump: all` on ESP8266; use `dump: raw` (or limited protocols).
- Bound learned capture output to prevent OOM.
- Keep `buffer_size` within stable heap limits (7kb worked in testing).
