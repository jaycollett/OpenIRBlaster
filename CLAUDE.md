# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

Home Assistant custom integration that manages an IR code library (learn, store, name, send) for OpenIRBlaster ESPHome devices. The integration owns all code storage and management; the ESPHome firmware is "dumb" (learn + transmit only).

**Target:** Python 3.12+, Home Assistant 2024.1+
**Hardware:** ESP8266 ESPHome device with IR TX (GPIO14) and IR RX TSOP38238 (GPIO5)

## Architecture

### Component responsibilities
- **ESPHome firmware**: Receives IR frames, fires `esphome.openirblaster_learned` events to HA, provides `send_ir_raw` service
- **HA integration** (`custom_components/openirblaster/`): Config flow, event listener, storage manager, entity provider (buttons per code)
- **Storage**: `.storage/openirblaster_<entry_id>.json` - persistent code library (schema in spec section 5.2)

### Data flow
1. User presses "Learn" button → integration enables learning mode switch on ESPHome device
2. Device receives IR → fires `esphome.openirblaster_learned` event with `{device_id, carrier_hz, pulses_json, timestamp, rssi}`
3. Integration captures event → prompts user for code name via options flow
4. User saves → integration writes to `.storage/` and creates/updates Button entity
5. User presses code button → integration calls ESPHome `send_ir_raw` service with stored payload

### Learning state machine (per device)
States: `IDLE` → `ARMED` (learning active) → `RECEIVED` (pending code) → `SAVED`/`CANCELLED`/`TIMEOUT`
Timeout: 30 seconds default

### ESPHome contract
Integration expects these from the firmware:
- **Switch**: `switch.<device>_ir_learning_mode`
- **Service**: `esphome.<device>_send_ir_raw(carrier_hz: int, code: int[])`
- **Event**: `esphome.openirblaster_learned` with payload containing `device_id`, `carrier_hz`, `pulses_json` (JSON string of int array), `timestamp`, `rssi` (optional)

## Development commands

### Setup development environment
```bash
# Create virtual environment
python3.12 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements_dev.txt

# Install pre-commit hooks (if configured)
pre-commit install
```

### Testing
```bash
# Run all tests
pytest

# Run specific test file
pytest tests/test_storage.py

# Run with coverage
pytest --cov=custom_components.openirblaster --cov-report=term-missing

# Run tests matching pattern
pytest -k "test_learning"
```

### Manual testing with Home Assistant
```bash
# Symlink to HA config directory
ln -s $(pwd)/custom_components/openirblaster ~/.homeassistant/custom_components/

# Restart HA to load integration
# Then add integration via UI: Settings → Devices & Services → Add Integration → OpenIRBlaster
```

### Code validation
```bash
# Type checking (if mypy configured)
mypy custom_components/openirblaster

# Linting (if configured)
ruff check custom_components/openirblaster
```

## Key implementation details

### Storage schema
- Location: `.storage/openirblaster_<config_entry_id>.json`
- Version: 1 (see spec section 5.2 for full schema)
- Code IDs: lowercase alphanumeric + underscore slugs, must be unique per device
- Collision resolution: append `_2`, `_3`, etc. if name already exists

### Entity naming conventions
- Learn button: `button.openirblaster_<entry>_learn`
- Send last button: `button.openirblaster_<entry>_send_last`
- Code buttons: `button.openirblaster_<entry>_<code_id>` (one per saved code)
- Sensors: `sensor.openirblaster_<entry>_last_learned_*` (name, timestamp, length)

### Config entry data structure
Each config entry must store:
- `learning_switch_entity_id`: default `switch.<device>_ir_learning_mode`
- `device_id`: ESPHome device identifier for event filtering
- `esphome_device_name`: used to construct service name `esphome.<name>_send_ir_raw`

### Event handling
- Subscribe to HA event bus for `esphome.openirblaster_learned`
- Filter by `event.data.device_id` matching config entry
- Parse `pulses_json` string into int array, validate bounded to 2000 elements max
- Store as pending in memory, prompt user via options flow

### Error handling patterns
- Failed transmit service call → log error + `persistent_notification.create`
- Missing/unavailable learning switch → create repair issue via `issue_registry`
- Oversized payload → reject with user-facing message
- Learning timeout → disable learning switch, show notification

## Module responsibilities

- `storage.py`: JSON load/save, schema migrations, ID slugging and collision resolution
- `learning.py`: State machine, event subscription/filtering, timeout handling
- `config_flow.py`: Discovery of ESPHome devices, entity ID validation, options flow for saving pending codes
- `button.py`: Learn button, send-last button, and dynamic per-code button entities
- `sensor.py`: Last learned metadata sensors
- `services.py`: Integration-level services (`openirblaster.learn_start`, `openirblaster.send_code`, etc.)
- `coordinator.py`: Optional DataUpdateCoordinator for shared state

## Phase 1 UX approach

Since immediate dialog prompts require frontend components (phase 2), phase 1 uses **options flow**:
1. User presses "Learn" button entity
2. Integration enables learning mode and waits for event
3. When event received, code stored as `pending_code` in memory
4. User navigates to integration options in UI
5. Options flow displays pending code, prompts for name, saves to storage
6. Button entity appears for the new code

## Critical implementation notes

- **One learning session per device**: Enforce with state machine lock
- **Pulse array bounds**: Reject payloads exceeding 2000 elements (firmware should truncate first)
- **ID stability**: Code IDs must remain stable across renames (ID derived from original name, user-facing name can change)
- **Entity registry cleanup**: When code deleted, remove corresponding button entity from registry
- **Device registry**: Register one HA device per config entry (manufacturer: OpenIRBlaster, model: ESP8266 IR Blaster)

## Testing strategy

### Unit tests (`pytest-homeassistant-custom-component`)
- Storage: read/write, migrations, ID collision resolution
- Learning state machine: transitions, timeouts, event filtering
- Service calls: verify `hass.services.async_call` invoked with correct payload
- Entity creation: verify buttons created/removed on code save/delete

### Integration tests
- Simulate `esphome.openirblaster_learned` event on bus → verify entity appears
- Config flow: mock ESPHome device discovery
- End-to-end: learn → save → send cycle (mocked ESPHome service)

### Manual testing checklist
- Add integration via UI with real ESPHome device
- Learn code, verify event received and pending state
- Save code via options flow, verify button entity appears
- Press button, verify IR transmits (observe device behavior)
- Rename code, verify entity updates
- Delete code, verify entity removed
- Restart HA, verify codes persist and entities recreate
- Test with multiple devices

## Reference

Full specification: `openirblaster_ha_integration_spec.md`
