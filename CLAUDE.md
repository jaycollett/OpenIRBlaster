# CLAUDE.md

Do not make any changes until you have 95% confidence in what you need to build. Ask me follow-up questions until you reach that confidence.

## Project Overview

Home Assistant custom integration for OpenIRBlaster ESPHome devices. Manages an IR code library (learn, store, name, send). The integration owns all code storage; the ESPHome firmware is "dumb" (learn + transmit only).

**Target:** Python 3.12+, Home Assistant 2024.1+

## Commands

```bash
pytest                                                    # All tests
pytest --cov=custom_components.openirblaster              # With coverage
pytest -k "test_learning"                                 # Pattern match
```

## Architecture

- **ESPHome firmware**: Fires `esphome.openirblaster_learned` events, provides `send_ir_raw` service
- **HA integration** (`custom_components/openirblaster/`): Config flow, event listener, storage manager, entity provider
- **Storage**: `.storage/openirblaster_<entry_id>.json` - persistent code library

### Data Flow

1. User presses "Learn" button -> integration enables learning mode switch on device
2. Device receives IR -> fires event with `{device_id, carrier_hz, pulses_json, timestamp, rssi}`
3. Integration captures event -> user names code via options flow
4. User saves -> writes to `.storage/` and creates Button entity
5. User presses code button -> calls ESPHome `send_ir_raw` with stored payload

### Learning State Machine

States: `IDLE` -> `ARMED` -> `RECEIVED` -> `SAVED`/`CANCELLED`/`TIMEOUT` (30s default)

## Critical Constraints

- One learning session per device (state machine lock)
- Pulse array max 2000 elements
- Code IDs must remain stable across renames (ID from original name)
- Entity registry cleanup required when code deleted
- Phase 1 uses options flow for code naming (no dialog prompts)

## Module Map

- `storage.py` - JSON persistence, schema migrations, ID slugging
- `learning.py` - State machine, event subscription, timeout
- `config_flow.py` - ESPHome discovery, options flow for saving codes
- `button.py` - Learn, send-last, and per-code button entities
- `sensor.py` - Last learned metadata sensors
- `services.py` - Integration-level services
