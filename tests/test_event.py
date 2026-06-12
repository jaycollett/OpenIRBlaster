"""Tests for the OpenIRBlaster event platform."""

from __future__ import annotations

from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_platform as ep, entity_registry as er

from custom_components.openirblaster.const import (
    DOMAIN,
    EVENT_TYPE_CODE_LEARNED,
    EVENT_TYPE_CODE_SAVED,
    SERVICE_SAVE_PENDING,
    STATE_RECEIVED,
    UNIQUE_ID_CODE_ACTIVITY_EVENT,
)
from custom_components.openirblaster.event import CodeActivityEvent
from custom_components.openirblaster.learning import LearnedCode


async def _async_setup_real_entry(
    hass: HomeAssistant, data: dict
) -> MockConfigEntry:
    """Set up an entry with real platforms."""
    entry = MockConfigEntry(domain=DOMAIN, data=data)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _event_entity_id(hass: HomeAssistant, entry: MockConfigEntry) -> str | None:
    registry = er.async_get(hass)
    return registry.async_get_entity_id(
        "event",
        DOMAIN,
        UNIQUE_ID_CODE_ACTIVITY_EVENT.format(entry_id=entry.entry_id),
    )


def _simulate_capture(entry: MockConfigEntry, rssi: int | None = -45) -> None:
    """Drive the session to RECEIVED with a learned code and notify."""
    session = entry.runtime_data.learning_session
    session._state = STATE_RECEIVED
    session._pending_code = LearnedCode(
        carrier_hz=38000,
        pulses=[9000, -4500, 560, -560],
        timestamp="2026-01-12T14:30:00-05:00",
        device_id="openirblaster-test123",
        rssi=rssi,
    )
    session._notify_state_change()


async def test_event_entity_created_unknown(
    hass: HomeAssistant, mock_config_entry_data: dict
) -> None:
    """The event entity exists, uncategorized, with no event fired yet."""
    entry = await _async_setup_real_entry(hass, mock_config_entry_data)

    entity_id = _event_entity_id(hass, entry)
    assert entity_id is not None

    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == "unknown"
    assert sorted(state.attributes["event_types"]) == [
        EVENT_TYPE_CODE_LEARNED,
        EVENT_TYPE_CODE_SAVED,
    ]

    # Users automate on these events: not relegated to DIAGNOSTIC
    registry = er.async_get(hass)
    assert registry.async_get(entity_id).entity_category is None


async def test_capture_fires_code_learned(
    hass: HomeAssistant, mock_config_entry_data: dict
) -> None:
    """A finalized capture fires code_learned with the capture metadata."""
    entry = await _async_setup_real_entry(hass, mock_config_entry_data)
    entity_id = _event_entity_id(hass, entry)

    _simulate_capture(entry, rssi=-45)
    await hass.async_block_till_done()

    state = hass.states.get(entity_id)
    assert state.state != "unknown"
    assert state.attributes["event_type"] == EVENT_TYPE_CODE_LEARNED
    assert state.attributes["carrier_hz"] == 38000
    assert state.attributes["pulse_count"] == 4
    assert state.attributes["timestamp"] == "2026-01-12T14:30:00-05:00"
    assert state.attributes["rssi"] == -45


async def test_capture_without_rssi_omits_attribute(
    hass: HomeAssistant, mock_config_entry_data: dict
) -> None:
    """Captures from firmware without RSSI omit the attribute cleanly."""
    entry = await _async_setup_real_entry(hass, mock_config_entry_data)
    entity_id = _event_entity_id(hass, entry)

    _simulate_capture(entry, rssi=None)
    await hass.async_block_till_done()

    state = hass.states.get(entity_id)
    assert state.attributes["event_type"] == EVENT_TYPE_CODE_LEARNED
    assert "rssi" not in state.attributes


async def test_save_fires_code_saved(
    hass: HomeAssistant, mock_config_entry_data: dict
) -> None:
    """Saving a pending code fires code_saved with the stored identity."""
    entry = await _async_setup_real_entry(hass, mock_config_entry_data)
    entity_id = _event_entity_id(hass, entry)

    session = entry.runtime_data.learning_session
    session._state = STATE_RECEIVED
    session._pending_code = LearnedCode(
        carrier_hz=40000,
        pulses=[9000, -4500, 560],
        timestamp="2026-01-12T14:30:00-05:00",
        device_id="openirblaster-test123",
    )

    await hass.services.async_call(
        DOMAIN,
        SERVICE_SAVE_PENDING,
        {"config_entry_id": entry.entry_id, "name": "TV Power"},
        blocking=True,
    )
    await hass.async_block_till_done()

    state = hass.states.get(entity_id)
    assert state.attributes["event_type"] == EVENT_TYPE_CODE_SAVED
    assert state.attributes["code_id"] == "tv_power"
    assert state.attributes["name"] == "TV Power"
    assert state.attributes["carrier_hz"] == 40000
    assert state.attributes["pulse_count"] == 3


async def test_event_entity_cleans_up(
    hass: HomeAssistant, mock_config_entry_data: dict
) -> None:
    """Removal unregisters the session callback; unload removes the state."""
    entry = await _async_setup_real_entry(hass, mock_config_entry_data)
    entity_id = _event_entity_id(hass, entry)
    session = entry.runtime_data.learning_session

    # Locate the live entity object and confirm its callback is registered
    event_entity: CodeActivityEvent | None = None
    for platform in ep.async_get_platforms(hass, DOMAIN):
        for entity in platform.entities.values():
            if isinstance(entity, CodeActivityEvent):
                event_entity = entity
    assert event_entity is not None
    assert event_entity._handle_state_change in session._callbacks

    await event_entity.async_remove()
    assert event_entity._handle_state_change not in session._callbacks

    # Full unload tears the live entity down (registered entities keep a
    # restored placeholder state, marked unavailable)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    state = hass.states.get(entity_id)
    assert state is None or state.state == "unavailable"
