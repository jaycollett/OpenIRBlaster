"""Tests for learning session module."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock

import pytest

from homeassistant.core import Event, HomeAssistant

from custom_components.openirblaster.const import (
    ATTR_CARRIER_HZ,
    ATTR_DEVICE_ID,
    ATTR_MAC_ADDRESS,
    ATTR_PULSES_JSON,
    ATTR_TIMESTAMP,
    EVENT_LEARNED,
    STATE_ARMED,
    STATE_CANCELLED,
    STATE_IDLE,
    STATE_RECEIVED,
    STATE_TIMEOUT,
)
from custom_components.openirblaster.learning import LearnedCode, LearningSession


@pytest.fixture
def learning_session(hass: HomeAssistant) -> LearningSession:
    """Create a learning session fixture."""
    return LearningSession(
        hass=hass,
        config_entry_id="test_entry",
        device_id="openirblaster-test123",
        learning_switch_entity_id="switch.openirblaster_test_ir_learning_mode",
        timeout=5,  # Short timeout for tests
    )


@pytest.fixture
def learning_session_with_mac(hass: HomeAssistant) -> LearningSession:
    """Create a learning session fixture with MAC address."""
    return LearningSession(
        hass=hass,
        config_entry_id="test_entry",
        device_id="openirblaster-test123",
        learning_switch_entity_id="switch.openirblaster_test_ir_learning_mode",
        mac_address="AA:BB:CC:DD:EE:FF",
        timeout=5,  # Short timeout for tests
    )


async def test_initial_state(learning_session: LearningSession) -> None:
    """Test initial state of learning session."""
    assert learning_session.state == STATE_IDLE
    assert learning_session.pending_code is None


async def test_start_learning(
    hass: HomeAssistant, learning_session: LearningSession
) -> None:
    """Test starting a learning session."""
    # Register a mock switch service
    calls = []

    async def mock_turn_on(call):
        calls.append(call)

    hass.services.async_register("switch", "turn_on", mock_turn_on)

    success = await learning_session.async_start_learning()
    assert success
    assert learning_session.state == STATE_ARMED

    # Verify learning switch was turned on
    assert len(calls) == 1
    assert calls[0].data["entity_id"] == "switch.openirblaster_test_ir_learning_mode"

    # Cleanup
    await learning_session.async_cleanup()


async def test_cannot_start_learning_when_not_idle(
    hass: HomeAssistant, learning_session: LearningSession
) -> None:
    """Test that learning cannot start when not in IDLE state."""
    hass.services.async_register("switch", "turn_on", AsyncMock())

    # Start first learning session
    await learning_session.async_start_learning()
    assert learning_session.state == STATE_ARMED

    # Try to start another
    success = await learning_session.async_start_learning()
    assert not success
    assert learning_session.state == STATE_ARMED

    # Cleanup
    await learning_session.async_cleanup()


async def test_handle_learned_event(
    hass: HomeAssistant, learning_session: LearningSession
) -> None:
    """Test handling a learned event."""
    hass.services.async_register("switch", "turn_on", AsyncMock())
    hass.services.async_register("switch", "turn_off", AsyncMock())

    await learning_session.async_start_learning()

    # Create learned event
    event_data = {
        ATTR_DEVICE_ID: "openirblaster-test123",
        ATTR_CARRIER_HZ: 38000,
        ATTR_PULSES_JSON: "[9000,-4500,560,-560]",
        ATTR_TIMESTAMP: "2026-01-12T14:30:00-05:00",
    }

    event = Event(EVENT_LEARNED, event_data)

    # Handle the event
    learning_session._async_handle_learned_event(event)

    # Give async tasks time to complete
    await asyncio.sleep(0.1)

    assert learning_session.state == STATE_RECEIVED
    assert learning_session.pending_code is not None
    assert learning_session.pending_code.carrier_hz == 38000
    assert learning_session.pending_code.pulses == [9000, -4500, 560, -560]


async def test_ignore_event_from_different_device(
    hass: HomeAssistant, learning_session: LearningSession
) -> None:
    """Test that events from different devices are ignored."""
    hass.services.async_register("switch", "turn_on", AsyncMock())

    await learning_session.async_start_learning()

    # Create event from different device
    event_data = {
        ATTR_DEVICE_ID: "openirblaster-different",
        ATTR_CARRIER_HZ: 38000,
        ATTR_PULSES_JSON: "[9000,-4500]",
    }

    event = Event(EVENT_LEARNED, event_data)
    learning_session._async_handle_learned_event(event)

    await asyncio.sleep(0.1)

    # Should still be armed, not received
    assert learning_session.state == STATE_ARMED
    assert learning_session.pending_code is None

    # Cleanup
    await learning_session.async_cleanup()


async def test_invalid_pulses_json(
    hass: HomeAssistant, learning_session: LearningSession
) -> None:
    """Test handling invalid JSON in pulses_json."""
    hass.services.async_register("switch", "turn_on", AsyncMock())
    hass.services.async_register("switch", "turn_off", AsyncMock())

    await learning_session.async_start_learning()

    # Create event with invalid JSON
    event_data = {
        ATTR_DEVICE_ID: "openirblaster-test123",
        ATTR_CARRIER_HZ: 38000,
        ATTR_PULSES_JSON: "not valid json[",
    }

    event = Event(EVENT_LEARNED, event_data)

    learning_session._async_handle_learned_event(event)
    await asyncio.sleep(0.1)

    # Should be cancelled due to invalid data
    assert learning_session.state == STATE_CANCELLED


async def test_learning_timeout(
    hass: HomeAssistant, learning_session: LearningSession
) -> None:
    """Test learning session timeout."""
    hass.services.async_register("switch", "turn_on", AsyncMock())
    hass.services.async_register("switch", "turn_off", AsyncMock())

    await learning_session.async_start_learning()
    assert learning_session.state == STATE_ARMED

    # Wait for timeout (5 seconds + buffer)
    await asyncio.sleep(5.5)

    assert learning_session.state == STATE_TIMEOUT
    assert learning_session.pending_code is None


async def test_clear_pending(
    hass: HomeAssistant, learning_session: LearningSession
) -> None:
    """Test clearing pending code."""
    hass.services.async_register("switch", "turn_on", AsyncMock())
    hass.services.async_register("switch", "turn_off", AsyncMock())

    await learning_session.async_start_learning()

    event_data = {
        ATTR_DEVICE_ID: "openirblaster-test123",
        ATTR_CARRIER_HZ: 38000,
        ATTR_PULSES_JSON: "[9000,-4500]",
    }

    event = Event(EVENT_LEARNED, event_data)

    learning_session._async_handle_learned_event(event)
    await asyncio.sleep(0.1)

    assert learning_session.state == STATE_RECEIVED
    assert learning_session.pending_code is not None

    # Clear pending (async operation, need to wait)
    learning_session.clear_pending()
    await asyncio.sleep(0.1)  # Wait for async task to complete
    assert learning_session.state == STATE_IDLE
    assert learning_session.pending_code is None


async def test_state_change_callback(
    hass: HomeAssistant, learning_session: LearningSession
) -> None:
    """Test state change callbacks."""
    callback_calls = []

    def callback(state: str, code: LearnedCode | None) -> None:
        callback_calls.append((state, code))

    learning_session.register_callback(callback)

    hass.services.async_register("switch", "turn_on", AsyncMock())

    await learning_session.async_start_learning()

    # Should have been called once for ARMED state
    assert len(callback_calls) == 1
    assert callback_calls[0][0] == STATE_ARMED
    assert callback_calls[0][1] is None

    # Cleanup
    await learning_session.async_cleanup()


async def test_oversized_pulse_array(
    hass: HomeAssistant, learning_session: LearningSession
) -> None:
    """Test rejection of oversized pulse arrays."""
    hass.services.async_register("switch", "turn_on", AsyncMock())
    hass.services.async_register("switch", "turn_off", AsyncMock())

    await learning_session.async_start_learning()

    # Create event with oversized pulse array (> 2000)
    large_pulses = [500] * 2500
    event_data = {
        ATTR_DEVICE_ID: "openirblaster-test123",
        ATTR_CARRIER_HZ: 38000,
        ATTR_PULSES_JSON: json.dumps(large_pulses),
    }

    event = Event(EVENT_LEARNED, event_data)

    learning_session._async_handle_learned_event(event)
    await asyncio.sleep(0.1)

    # Should be cancelled due to oversized array
    assert learning_session.state == STATE_CANCELLED
    assert learning_session.pending_code is None


async def test_cleanup(
    hass: HomeAssistant, learning_session: LearningSession
) -> None:
    """Test session cleanup."""
    hass.services.async_register("switch", "turn_on", AsyncMock())

    await learning_session.async_start_learning()
    assert learning_session._event_listener is not None
    assert learning_session._timeout_handle is not None

    await learning_session.async_cleanup()

    # Cleanup should cancel timeout and remove listener
    assert learning_session._timeout_handle is None
    assert learning_session._event_listener is None


async def test_handle_event_with_mac_address_match(
    hass: HomeAssistant, learning_session_with_mac: LearningSession
) -> None:
    """Test that events with matching MAC address are accepted."""
    hass.services.async_register("switch", "turn_on", AsyncMock())
    hass.services.async_register("switch", "turn_off", AsyncMock())

    await learning_session_with_mac.async_start_learning()

    # Create event with matching MAC address (case-insensitive)
    event_data = {
        ATTR_DEVICE_ID: "openirblaster-test123",
        ATTR_MAC_ADDRESS: "aa:bb:cc:dd:ee:ff",  # lowercase version
        ATTR_CARRIER_HZ: 38000,
        ATTR_PULSES_JSON: "[9000,-4500,560,-560]",
        ATTR_TIMESTAMP: "2026-01-12T14:30:00-05:00",
    }

    event = Event(EVENT_LEARNED, event_data)
    learning_session_with_mac._async_handle_learned_event(event)

    await asyncio.sleep(0.1)

    assert learning_session_with_mac.state == STATE_RECEIVED
    assert learning_session_with_mac.pending_code is not None


async def test_handle_event_with_different_mac_but_matching_device_id(
    hass: HomeAssistant, learning_session_with_mac: LearningSession
) -> None:
    """Test that events with different MAC but matching device_id are rejected when MAC is configured."""
    hass.services.async_register("switch", "turn_on", AsyncMock())

    await learning_session_with_mac.async_start_learning()

    # Create event with different MAC but matching device_id
    event_data = {
        ATTR_DEVICE_ID: "openirblaster-test123",
        ATTR_MAC_ADDRESS: "11:22:33:44:55:66",  # different MAC
        ATTR_CARRIER_HZ: 38000,
        ATTR_PULSES_JSON: "[9000,-4500,560,-560]",
    }

    event = Event(EVENT_LEARNED, event_data)
    learning_session_with_mac._async_handle_learned_event(event)

    await asyncio.sleep(0.1)

    # Should remain armed because MAC doesn't match
    assert learning_session_with_mac.state == STATE_ARMED
    assert learning_session_with_mac.pending_code is None

    await learning_session_with_mac.async_cleanup()


async def test_handle_event_with_mac_fallback_to_device_id(
    hass: HomeAssistant, learning_session_with_mac: LearningSession
) -> None:
    """Test that events without MAC address fall back to device_id matching."""
    hass.services.async_register("switch", "turn_on", AsyncMock())
    hass.services.async_register("switch", "turn_off", AsyncMock())

    await learning_session_with_mac.async_start_learning()

    # Create event without MAC address (old firmware)
    event_data = {
        ATTR_DEVICE_ID: "openirblaster-test123",
        # No MAC address in event
        ATTR_CARRIER_HZ: 38000,
        ATTR_PULSES_JSON: "[9000,-4500,560,-560]",
        ATTR_TIMESTAMP: "2026-01-12T14:30:00-05:00",
    }

    event = Event(EVENT_LEARNED, event_data)
    learning_session_with_mac._async_handle_learned_event(event)

    await asyncio.sleep(0.1)

    # Should accept because device_id matches as fallback
    assert learning_session_with_mac.state == STATE_RECEIVED
    assert learning_session_with_mac.pending_code is not None


async def test_session_without_mac_accepts_matching_device_id(
    hass: HomeAssistant, learning_session: LearningSession
) -> None:
    """Test that session without MAC configured accepts events by device_id."""
    hass.services.async_register("switch", "turn_on", AsyncMock())
    hass.services.async_register("switch", "turn_off", AsyncMock())

    await learning_session.async_start_learning()

    # Create event with MAC address (from new firmware) but session has no MAC
    event_data = {
        ATTR_DEVICE_ID: "openirblaster-test123",
        ATTR_MAC_ADDRESS: "aa:bb:cc:dd:ee:ff",
        ATTR_CARRIER_HZ: 38000,
        ATTR_PULSES_JSON: "[9000,-4500,560,-560]",
        ATTR_TIMESTAMP: "2026-01-12T14:30:00-05:00",
    }

    event = Event(EVENT_LEARNED, event_data)
    learning_session._async_handle_learned_event(event)

    await asyncio.sleep(0.1)

    # Should accept because device_id matches
    assert learning_session.state == STATE_RECEIVED
    assert learning_session.pending_code is not None


# ---------------------------------------------------------------------------
# Text_sensor fallback path (issue #8): when the ESPHome API socket drops the
# learned event, the text_sensor state replays on reconnect. We must capture
# the code via that path identically to the event path.
# ---------------------------------------------------------------------------

# Matches the pattern in learning._resolve_text_sensor_entity_id:
# sensor.{device_id slug}_last_learned_ir_payload
_TEXT_SENSOR_ENTITY_ID = "sensor.openirblaster_test123_last_learned_ir_payload"

_GOOD_TEXT_SENSOR_PAYLOAD = json.dumps(
    {
        "device_id": "openirblaster-test123",
        "carrier_hz": 38000,
        "rssi": -45,
        "timestamp": "2026-01-12T14:30:00-05:00",
        "pulses": [9000, -4500, 560, -560],
    }
)


async def test_text_sensor_fallback_captures_code(
    hass: HomeAssistant, learning_session: LearningSession
) -> None:
    """State change on the payload text_sensor captures the code when the event is lost."""
    hass.services.async_register("switch", "turn_on", AsyncMock())
    hass.services.async_register("switch", "turn_off", AsyncMock())

    # Pre-populate the text_sensor so the resolver finds it
    hass.states.async_set(_TEXT_SENSOR_ENTITY_ID, "")

    await learning_session.async_start_learning()
    assert learning_session._state_listener is not None
    # Pin the resolved entity_id so the test doesn't silently become a no-op
    # if the slug heuristic ever drifts and subscribes to a different entity
    # than the one we publish state to below.
    assert learning_session._text_sensor_entity_id == _TEXT_SENSOR_ENTITY_ID

    # Simulate the firmware publishing the learned payload on reconnect
    hass.states.async_set(_TEXT_SENSOR_ENTITY_ID, _GOOD_TEXT_SENSOR_PAYLOAD)
    await hass.async_block_till_done()
    await asyncio.sleep(0.1)

    assert learning_session.state == STATE_RECEIVED
    assert learning_session.pending_code is not None
    assert learning_session.pending_code.carrier_hz == 38000
    assert learning_session.pending_code.pulses == [9000, -4500, 560, -560]


async def test_event_first_deduplicates_text_sensor(
    hass: HomeAssistant, learning_session: LearningSession
) -> None:
    """When the event arrives first, a later text_sensor state change is ignored."""
    hass.services.async_register("switch", "turn_on", AsyncMock())
    hass.services.async_register("switch", "turn_off", AsyncMock())

    hass.states.async_set(_TEXT_SENSOR_ENTITY_ID, "")
    await learning_session.async_start_learning()

    # Event arrives first
    event = Event(
        EVENT_LEARNED,
        {
            ATTR_DEVICE_ID: "openirblaster-test123",
            ATTR_CARRIER_HZ: 38000,
            ATTR_PULSES_JSON: "[9000,-4500]",
            ATTR_TIMESTAMP: "2026-01-12T14:30:00-05:00",
        },
    )
    learning_session._async_handle_learned_event(event)
    await asyncio.sleep(0.1)

    assert learning_session.state == STATE_RECEIVED
    first_pulses = list(learning_session.pending_code.pulses)
    assert first_pulses == [9000, -4500]

    # A late text_sensor payload (different pulses) must not overwrite
    hass.states.async_set(
        _TEXT_SENSOR_ENTITY_ID,
        json.dumps(
            {
                "device_id": "openirblaster-test123",
                "carrier_hz": 38000,
                "pulses": [1111, -2222, 3333],
                "timestamp": "2026-01-12T14:30:01-05:00",
            }
        ),
    )
    await hass.async_block_till_done()
    await asyncio.sleep(0.1)

    # Pending code unchanged
    assert learning_session.pending_code.pulses == first_pulses


async def test_text_sensor_first_deduplicates_event(
    hass: HomeAssistant, learning_session: LearningSession
) -> None:
    """When the text_sensor fires first, a subsequent event is ignored."""
    hass.services.async_register("switch", "turn_on", AsyncMock())
    hass.services.async_register("switch", "turn_off", AsyncMock())

    hass.states.async_set(_TEXT_SENSOR_ENTITY_ID, "")
    await learning_session.async_start_learning()

    # Text_sensor fires first (simulates dropped event)
    hass.states.async_set(_TEXT_SENSOR_ENTITY_ID, _GOOD_TEXT_SENSOR_PAYLOAD)
    await hass.async_block_till_done()
    await asyncio.sleep(0.1)
    assert learning_session.state == STATE_RECEIVED
    first_pulses = list(learning_session.pending_code.pulses)

    # Late event arrives with different data; must not re-trigger finalize
    late_event = Event(
        EVENT_LEARNED,
        {
            ATTR_DEVICE_ID: "openirblaster-test123",
            ATTR_CARRIER_HZ: 40000,
            ATTR_PULSES_JSON: "[1,2,3,4]",
            ATTR_TIMESTAMP: "2026-01-12T14:30:02-05:00",
        },
    )
    learning_session._async_handle_learned_event(late_event)
    await asyncio.sleep(0.1)

    assert learning_session.pending_code.pulses == first_pulses
    assert learning_session.pending_code.carrier_hz == 38000


async def test_text_sensor_invalid_json_cancels_cleanly(
    hass: HomeAssistant, learning_session: LearningSession
) -> None:
    """Invalid JSON on the text_sensor should cancel the session."""
    hass.services.async_register("switch", "turn_on", AsyncMock())
    hass.services.async_register("switch", "turn_off", AsyncMock())

    hass.states.async_set(_TEXT_SENSOR_ENTITY_ID, "")
    await learning_session.async_start_learning()
    assert learning_session.state == STATE_ARMED

    hass.states.async_set(_TEXT_SENSOR_ENTITY_ID, "{not valid json")
    await hass.async_block_till_done()
    await asyncio.sleep(0.1)

    assert learning_session.state == STATE_CANCELLED
    assert learning_session.pending_code is None


async def test_text_sensor_empty_payload_is_ignored(
    hass: HomeAssistant, learning_session: LearningSession
) -> None:
    """Empty-string publishes (e.g. the 'Clear' button on the device) are noise."""
    hass.services.async_register("switch", "turn_on", AsyncMock())
    hass.services.async_register("switch", "turn_off", AsyncMock())

    hass.states.async_set(_TEXT_SENSOR_ENTITY_ID, "seed")
    await learning_session.async_start_learning()

    # Clear the sensor -> empty state. Must not cancel or transition.
    hass.states.async_set(_TEXT_SENSOR_ENTITY_ID, "")
    await hass.async_block_till_done()
    await asyncio.sleep(0.1)

    assert learning_session.state == STATE_ARMED
    assert learning_session.pending_code is None

    await learning_session.async_cleanup()


async def test_async_clear_pending_tears_down_listeners_and_timeout(
    hass: HomeAssistant, learning_session: LearningSession
) -> None:
    """async_clear_pending cancels the timeout and unsubscribes both listeners."""
    hass.services.async_register("switch", "turn_on", AsyncMock())
    hass.services.async_register("switch", "turn_off", AsyncMock())

    hass.states.async_set(_TEXT_SENSOR_ENTITY_ID, "")
    await learning_session.async_start_learning()
    assert learning_session._timeout_handle is not None
    assert learning_session._event_listener is not None
    assert learning_session._state_listener is not None

    # User dismisses without reaching STATE_RECEIVED
    await learning_session.async_clear_pending()

    # All subscriptions released, safe to start again
    assert learning_session._timeout_handle is None
    assert learning_session._event_listener is None
    assert learning_session._state_listener is None
    assert learning_session.state == STATE_IDLE
    assert learning_session.pending_code is None

    # Second call is a no-op (idempotent) and does not raise
    await learning_session.async_clear_pending()
    assert learning_session.state == STATE_IDLE


# ---------------------------------------------------------------------------
# Resolver and race-guard tests (QA follow-up to issue #8)
# ---------------------------------------------------------------------------


async def test_resolver_strategy_1_device_registry_by_mac(
    hass: HomeAssistant,
) -> None:
    """Strategy 1 finds the text_sensor via MAC even when the slug does not match.

    Regression guard: the resolver must not silently depend on Strategy 2's
    slug heuristic when a MAC is available. This test creates a device with
    only a MAC connection and a sensor whose entity_id would *not* match the
    Strategy 2 slug, proving Strategy 1 works independently.
    """
    from homeassistant.helpers import device_registry as dr, entity_registry as er

    dev_reg = dr.async_get(hass)
    ent_reg = er.async_get(hass)

    # Register a fake ESPHome config entry so the device can be attached to it
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    esphome_entry = MockConfigEntry(domain="esphome", data={})
    esphome_entry.add_to_hass(hass)

    # Device lives under the ESPHome integration with a MAC connection
    ha_device = dev_reg.async_get_or_create(
        config_entry_id=esphome_entry.entry_id,
        connections={(dr.CONNECTION_NETWORK_MAC, "aa:bb:cc:dd:ee:ff")},
        identifiers={("esphome", "aabbccddeeff")},
        name="Friendly Custom Name",
    )

    # Sensor entity attached to that device, with unique_id carrying the
    # firmware id. Crucially, the entity_id does NOT match the slug heuristic.
    ent_reg.async_get_or_create(
        domain="sensor",
        platform="esphome",
        unique_id="some-prefix-last_ir_raw_snippet",
        suggested_object_id="custom_named_payload",
        device_id=ha_device.id,
    )

    session = LearningSession(
        hass=hass,
        config_entry_id="test_entry",
        device_id="openirblaster-customname",
        learning_switch_entity_id="switch.x",
        mac_address="AA:BB:CC:DD:EE:FF",  # case differs on purpose
        timeout=5,
    )

    resolved = session._resolve_text_sensor_entity_id()
    assert resolved == "sensor.custom_named_payload"


async def test_resolver_returns_none_falls_back_to_event_path(
    hass: HomeAssistant, caplog
) -> None:
    """When neither resolver strategy finds the text_sensor, learning still works.

    The event path must remain subscribed (primary path) and the fallback
    simply logs a warning and is skipped. This covers the graceful-
    degradation contract documented in learning.py.
    """
    import logging

    # No MAC, no pre-populated entity, no matching registry entry.
    session = LearningSession(
        hass=hass,
        config_entry_id="test_entry",
        device_id="openirblaster-nonexistent-xyz",
        learning_switch_entity_id="switch.nonexistent_ir_learning_mode",
        timeout=5,
    )

    hass.services.async_register("switch", "turn_on", AsyncMock())

    caplog.set_level(
        logging.WARNING, logger="custom_components.openirblaster.learning"
    )
    success = await session.async_start_learning()

    try:
        assert success is True
        assert session._state_listener is None
        assert session._event_listener is not None
        assert any(
            "Could not resolve ESPHome payload text_sensor" in rec.message
            for rec in caplog.records
        )
    finally:
        await session.async_cleanup()


async def test_validation_failure_sets_finalized_flag_synchronously(
    hass: HomeAssistant, learning_session: LearningSession
) -> None:
    """A bad text_sensor payload must set `_capture_finalized = True` synchronously.

    This closes the S1/S2 race: if the flag were only flipped when the
    scheduled `_async_cancel` task finally ran, the other capture path
    (event or text_sensor) could slip a valid payload through the
    `STATE_ARMED + not finalized` guard in between. The subsequent cancel
    would then clobber a legitimately committed capture.

    We assert the flag is True *before* yielding to the event loop, which
    proves no interleaved handler can observe `_capture_finalized == False`.
    """
    hass.services.async_register("switch", "turn_on", AsyncMock())
    hass.services.async_register("switch", "turn_off", AsyncMock())

    hass.states.async_set(_TEXT_SENSOR_ENTITY_ID, "")
    await learning_session.async_start_learning()
    assert learning_session._capture_finalized is False

    # Directly invoke the text_sensor handler with a bad payload. The handler
    # is a @callback (sync), so by the time it returns, the guard must have
    # been flipped even though _async_cancel is still a pending task.
    bad_new_state = type(
        "S", (), {"state": "{not valid json", "entity_id": _TEXT_SENSOR_ENTITY_ID}
    )()
    event = Event(
        "state_changed",
        {
            "entity_id": _TEXT_SENSOR_ENTITY_ID,
            "old_state": None,
            "new_state": bad_new_state,
        },
    )
    learning_session._async_handle_text_sensor_state(event)

    # Flag is set synchronously, before any await has run the cancel task
    assert learning_session._capture_finalized is True

    # Now fire a valid event. Because the flag is already True, the event
    # path must bail out and NOT commit the capture, even if cancel hasn't
    # run yet.
    valid_event = Event(
        EVENT_LEARNED,
        {
            ATTR_DEVICE_ID: "openirblaster-test123",
            ATTR_CARRIER_HZ: 38000,
            ATTR_PULSES_JSON: "[9000,-4500,560,-560]",
            ATTR_TIMESTAMP: "2026-01-12T14:30:00-05:00",
        },
    )
    learning_session._async_handle_learned_event(valid_event)

    # Drain the pending cancel task
    await asyncio.sleep(0.1)

    # No valid code committed; session cancelled, not received
    assert learning_session.pending_code is None
    assert learning_session.state == STATE_CANCELLED
