"""Tests for learning session module."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest

from homeassistant.core import Event, HomeAssistant

from custom_components.openirblaster.const import (
    ATTR_CARRIER_HZ,
    ATTR_DEVICE_ID,
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

    # Clear pending
    learning_session.clear_pending()
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
