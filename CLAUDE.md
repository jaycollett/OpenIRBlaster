# CLAUDE.md

## Project Overview

Home Assistant custom integration for OpenIRBlaster ESPHome devices. Manages an IR code library (learn, store, name, send). The integration owns all code storage; the ESPHome firmware is "dumb" (learn + transmit only).

**Target:** Python 3.12+, Home Assistant 2024.12+

## Commands

```bash
pytest                                                    # All tests
pytest --cov=custom_components.openirblaster              # With coverage
pytest -k "test_learning"                                 # Pattern match
```

## Learning State Machine

States: `IDLE` -> `ARMED` -> `RECEIVED` -> `SAVED`/`CANCELLED`/`TIMEOUT` (30s default)

## Critical Constraints

- One learning session per device (state machine lock)
- Pulse array max 2000 elements
- Code IDs must remain stable across renames (ID from original name)
- Entity registry cleanup required when code deleted
- Phase 1 uses options flow for code naming (no dialog prompts)
