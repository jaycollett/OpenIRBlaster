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


async def test_concurrent_start_learning_only_one_wins(
    hass: HomeAssistant, learning_session: LearningSession
) -> None:
    """Two concurrent starts must yield exactly one armed session.

    The IDLE check used to be followed by an await before the state was
    claimed, so two concurrent starts could both pass it; the second would
    overwrite the first's bus-listener unsubscribe callable (permanent
    leak) and leave a stray timeout. The state is now claimed synchronously
    before the first await, so the loser is rejected exactly like the
    existing non-IDLE path.
    """
    turn_on_started = asyncio.Event()
    release_turn_on = asyncio.Event()

    async def slow_turn_on(call) -> None:
        turn_on_started.set()
        await release_turn_on.wait()

    hass.services.async_register("switch", "turn_on", slow_turn_on)
    hass.services.async_register("switch", "turn_off", AsyncMock())

    baseline_listeners = hass.bus.async_listeners().get(EVENT_LEARNED, 0)

    task1 = hass.async_create_task(learning_session.async_start_learning())
    task2 = hass.async_create_task(learning_session.async_start_learning())

    # The first start is suspended inside the switch call; the second must
    # already have been rejected by the synchronous claim.
    await asyncio.wait_for(turn_on_started.wait(), timeout=1)
    release_turn_on.set()

    results = await asyncio.gather(task1, task2)
    assert sorted(results) == [False, True]
    assert learning_session.state == STATE_ARMED

    # Exactly one bus listener and one timeout were registered.
    assert (
        hass.bus.async_listeners().get(EVENT_LEARNED, 0) - baseline_listeners == 1
    )
    assert learning_session._event_listener is not None
    assert learning_session._timeout_unsub is not None

    await learning_session.async_cleanup()
    # Cleanup releases the single subscription completely.
    assert hass.bus.async_listeners().get(EVENT_LEARNED, 0) == baseline_listeners


async def test_start_learning_reverts_to_idle_on_switch_failure(
    hass: HomeAssistant, learning_session: LearningSession
) -> None:
    """A failed switch turn-on releases the claim and returns to IDLE."""

    async def failing_turn_on(call) -> None:
        raise RuntimeError("device offline")

    hass.services.async_register("switch", "turn_on", failing_turn_on)

    baseline_listeners = hass.bus.async_listeners().get(EVENT_LEARNED, 0)

    success = await learning_session.async_start_learning()
    assert success is False
    assert learning_session.state == STATE_IDLE
    assert learning_session._event_listener is None
    assert learning_session._timeout_unsub is None
    assert hass.bus.async_listeners().get(EVENT_LEARNED, 0) == baseline_listeners

    # The session is immediately startable again once the device recovers.
    hass.services.async_remove("switch", "turn_on")
    hass.services.async_register("switch", "turn_on", AsyncMock())
    assert await learning_session.async_start_learning() is True
    assert learning_session.state == STATE_ARMED
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
    await learning_session.async_clear_pending()
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
    assert learning_session._timeout_unsub is not None

    await learning_session.async_cleanup()

    # Cleanup should cancel timeout and remove listener
    assert learning_session._timeout_unsub is None
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


@pytest.mark.parametrize(
    "bad_mac",
    [
        "e\x0f",                 # 2-byte garbage from real bug report
        "\x90\x0e",              # high-byte garbage that fails UTF-8 at the wire
        "AA:BB:CC:DD:EE",        # missing one octet
        "AA-BB-CC-DD-EE-FF",     # wrong separator
        "ZZ:BB:CC:DD:EE:FF",     # non-hex chars
        "aabbccddeeff",          # no separators
    ],
)
async def test_malformed_event_mac_falls_back_to_device_id(
    hass: HomeAssistant, learning_session_with_mac: LearningSession, bad_mac: str
) -> None:
    """Test that a malformed event MAC is ignored and device_id matching takes over.

    Older firmware versions returned a dangling-pointer c_str() in the on_raw
    lambda, which produced garbage in the event's mac_address field. The
    session should treat that as if no MAC was supplied and accept the event
    if the device_id still matches.
    """
    hass.services.async_register("switch", "turn_on", AsyncMock())
    hass.services.async_register("switch", "turn_off", AsyncMock())

    await learning_session_with_mac.async_start_learning()

    event_data = {
        ATTR_DEVICE_ID: "openirblaster-test123",
        ATTR_MAC_ADDRESS: bad_mac,
        ATTR_CARRIER_HZ: 38000,
        ATTR_PULSES_JSON: "[9000,-4500,560,-560]",
        ATTR_TIMESTAMP: "2026-01-12T14:30:00-05:00",
    }

    event = Event(EVENT_LEARNED, event_data)
    learning_session_with_mac._async_handle_learned_event(event)

    await asyncio.sleep(0.1)

    # Malformed MAC should be dropped and device_id should match
    assert learning_session_with_mac.state == STATE_RECEIVED
    assert learning_session_with_mac.pending_code is not None


async def test_malformed_event_mac_rejected_when_device_id_also_mismatches(
    hass: HomeAssistant, learning_session_with_mac: LearningSession
) -> None:
    """Test that a malformed event MAC plus a wrong device_id is still rejected.

    The malformed-MAC fallback must not become a wildcard that lets
    cross-device events leak through.
    """
    hass.services.async_register("switch", "turn_on", AsyncMock())

    await learning_session_with_mac.async_start_learning()

    event_data = {
        ATTR_DEVICE_ID: "openirblaster-different",   # wrong device
        ATTR_MAC_ADDRESS: "e\x0f",                    # garbage MAC
        ATTR_CARRIER_HZ: 38000,
        ATTR_PULSES_JSON: "[9000,-4500,560,-560]",
    }

    event = Event(EVENT_LEARNED, event_data)
    learning_session_with_mac._async_handle_learned_event(event)

    await asyncio.sleep(0.1)

    # Wrong device_id with garbage MAC: should remain armed
    assert learning_session_with_mac.state == STATE_ARMED
    assert learning_session_with_mac.pending_code is None

    await learning_session_with_mac.async_cleanup()


async def test_malformed_mac_creates_repair_issue(
    hass: HomeAssistant, learning_session_with_mac: LearningSession
) -> None:
    """A malformed event MAC raises a dangling_mac repair issue."""
    from homeassistant.helpers import issue_registry as ir

    from custom_components.openirblaster.const import DOMAIN

    hass.services.async_register("switch", "turn_on", AsyncMock())
    hass.services.async_register("switch", "turn_off", AsyncMock())

    await learning_session_with_mac.async_start_learning()

    event = Event(
        EVENT_LEARNED,
        {
            ATTR_DEVICE_ID: "openirblaster-test123",
            ATTR_MAC_ADDRESS: "e\x0f",  # dangling-pointer garbage
            ATTR_CARRIER_HZ: 38000,
            ATTR_PULSES_JSON: "[9000,-4500,560,-560]",
            ATTR_TIMESTAMP: "2026-01-12T14:30:00-05:00",
        },
    )
    learning_session_with_mac._async_handle_learned_event(event)
    await asyncio.sleep(0.1)

    issue_registry = ir.async_get(hass)
    issue = issue_registry.async_get_issue(DOMAIN, "dangling_mac_test_entry")
    assert issue is not None
    assert issue.severity == ir.IssueSeverity.WARNING
    assert issue.translation_key == "dangling_mac"
    assert issue.is_fixable is False


async def test_valid_mac_clears_repair_issue(
    hass: HomeAssistant, learning_session_with_mac: LearningSession
) -> None:
    """A valid event MAC deletes a stale dangling_mac repair issue."""
    from homeassistant.helpers import issue_registry as ir

    from custom_components.openirblaster.const import DOMAIN

    # Pre-existing issue from a capture before the firmware was updated
    ir.async_create_issue(
        hass,
        DOMAIN,
        "dangling_mac_test_entry",
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key="dangling_mac",
        translation_placeholders={"device_id": "openirblaster-test123"},
    )

    hass.services.async_register("switch", "turn_on", AsyncMock())
    hass.services.async_register("switch", "turn_off", AsyncMock())

    await learning_session_with_mac.async_start_learning()

    event = Event(
        EVENT_LEARNED,
        {
            ATTR_DEVICE_ID: "openirblaster-test123",
            ATTR_MAC_ADDRESS: "AA:BB:CC:DD:EE:FF",  # valid again
            ATTR_CARRIER_HZ: 38000,
            ATTR_PULSES_JSON: "[9000,-4500,560,-560]",
            ATTR_TIMESTAMP: "2026-01-12T14:30:00-05:00",
        },
    )
    learning_session_with_mac._async_handle_learned_event(event)
    await asyncio.sleep(0.1)

    issue_registry = ir.async_get(hass)
    assert (
        issue_registry.async_get_issue(DOMAIN, "dangling_mac_test_entry") is None
    )
    assert learning_session_with_mac.state == STATE_RECEIVED


async def test_capture_at_deadline_does_not_emit_timeout(
    hass: HomeAssistant, learning_session: LearningSession
) -> None:
    """A capture landing right at the timeout deadline must win the race.

    The timeout handle must be cancelled synchronously inside the (sync)
    event handler, before the async finalize task runs, and a timeout
    callback that fires anyway must be a no-op: the session ends in
    RECEIVED and never transitions through TIMEOUT.
    """
    states: list[str] = []
    learning_session.register_callback(lambda state, code: states.append(state))

    hass.services.async_register("switch", "turn_on", AsyncMock())
    hass.services.async_register("switch", "turn_off", AsyncMock())

    await learning_session.async_start_learning()
    assert learning_session._timeout_unsub is not None

    event = Event(
        EVENT_LEARNED,
        {
            ATTR_DEVICE_ID: "openirblaster-test123",
            ATTR_CARRIER_HZ: 38000,
            ATTR_PULSES_JSON: "[9000,-4500,560,-560]",
            ATTR_TIMESTAMP: "2026-01-12T14:30:00-05:00",
        },
    )
    learning_session._async_handle_learned_event(event)

    # Cancelled synchronously in the (sync) event handler: the unsub
    # callable was invoked and cleared before any await could let the
    # deadline fire.
    assert learning_session._timeout_unsub is None

    # Simulate the deadline firing anyway (the loop callback had already
    # been dispatched when the capture arrived). Must be a no-op.
    await learning_session._async_handle_timeout()

    # Drain the finalize task.
    await asyncio.sleep(0.1)

    assert learning_session.state == STATE_RECEIVED
    assert learning_session.pending_code is not None
    assert STATE_TIMEOUT not in states


async def test_timeout_during_suspended_finalize_is_noop(
    hass: HomeAssistant, learning_session: LearningSession
) -> None:
    """Timeout firing while finalize awaits the switch turn-off is a no-op.

    While _async_finalize_learning is suspended on the blocking switch
    turn-off call, the state is still ARMED; only _capture_finalized tells
    the timeout handler the capture already won.
    """
    states: list[str] = []
    learning_session.register_callback(lambda state, code: states.append(state))

    turn_off_started = asyncio.Event()
    release_turn_off = asyncio.Event()

    async def slow_turn_off(call) -> None:
        turn_off_started.set()
        await release_turn_off.wait()

    hass.services.async_register("switch", "turn_on", AsyncMock())
    hass.services.async_register("switch", "turn_off", slow_turn_off)

    await learning_session.async_start_learning()

    event = Event(
        EVENT_LEARNED,
        {
            ATTR_DEVICE_ID: "openirblaster-test123",
            ATTR_CARRIER_HZ: 38000,
            ATTR_PULSES_JSON: "[9000,-4500,560,-560]",
            ATTR_TIMESTAMP: "2026-01-12T14:30:00-05:00",
        },
    )
    learning_session._async_handle_learned_event(event)

    # Let finalize start and suspend inside the switch turn-off call.
    await asyncio.wait_for(turn_off_started.wait(), timeout=1)
    assert learning_session.state == STATE_ARMED  # finalize not done yet

    # The deadline fires while finalize is suspended: must bail immediately.
    await learning_session._async_handle_timeout()
    assert STATE_TIMEOUT not in states

    # Unblock finalize and confirm the capture completes normally.
    release_turn_off.set()
    await asyncio.sleep(0.1)

    assert learning_session.state == STATE_RECEIVED
    assert learning_session.pending_code is not None
    assert STATE_TIMEOUT not in states


# ---------------------------------------------------------------------------
# Capture-marker replay path: the firmware publishes a short timestamp marker
# to a text_sensor after every learned capture. The marker state replays on
# API reconnect, so when the integration sees the marker change but no
# corresponding event arrives we ask the firmware to re-fire the event via
# the replay_last_ir service.
# ---------------------------------------------------------------------------

# Matches the pattern in learning._resolve_text_sensor_entity_id:
# sensor.{device_id slug}_last_ir_capture_marker
_CAPTURE_MARKER_ENTITY_ID = "sensor.openirblaster_test123_last_ir_capture_marker"

# Default send_ir_raw service name used in the tests. The replay service
# name is derived by replacing the suffix.
_SEND_SERVICE_NAME = "openirblaster_test123_send_ir_raw"
_REPLAY_SERVICE_NAME = "openirblaster_test123_replay_last_ir"


def _install_replay_service_mock(
    hass: HomeAssistant,
    config_entry_id: str = "test_entry",
    send_service: str = _SEND_SERVICE_NAME,
    replay_service: str = _REPLAY_SERVICE_NAME,
) -> AsyncMock:
    """Create a config entry with runtime_data so get_esphome_service
    resolves, and register a replay-service AsyncMock callers can assert
    against.
    """
    from unittest.mock import MagicMock

    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.openirblaster.const import DOMAIN
    from custom_components.openirblaster.data import OpenIRBlasterData

    entry = MockConfigEntry(domain=DOMAIN, entry_id=config_entry_id)
    entry.add_to_hass(hass)
    entry.runtime_data = OpenIRBlasterData(
        storage=MagicMock(),
        learning_session=MagicMock(),
        esphome_service_name=send_service,
    )
    replay_mock = AsyncMock()
    hass.services.async_register("esphome", replay_service, replay_mock)
    return replay_mock


async def test_marker_change_requests_replay_after_grace(
    hass: HomeAssistant, learning_session: LearningSession, monkeypatch
) -> None:
    """Marker state change with no event in the grace window triggers replay."""
    import custom_components.openirblaster.learning as learning_module

    monkeypatch.setattr(learning_module, "_REPLAY_GRACE_SECONDS", 0.1)
    replay_mock = _install_replay_service_mock(hass)

    hass.services.async_register("switch", "turn_on", AsyncMock())
    hass.services.async_register("switch", "turn_off", AsyncMock())

    hass.states.async_set(_CAPTURE_MARKER_ENTITY_ID, "")
    await learning_session.async_start_learning()
    assert learning_session._state_listener is not None
    assert learning_session._text_sensor_entity_id == _CAPTURE_MARKER_ENTITY_ID

    # Firmware publishes the marker. No event arrives.
    hass.states.async_set(_CAPTURE_MARKER_ENTITY_ID, "2026-05-20T12:00:00+0000")
    await hass.async_block_till_done()
    await asyncio.sleep(0.5)

    assert replay_mock.await_count == 1
    # Still armed; the replay service would now fire an event that finalizes.
    assert learning_session.state == STATE_ARMED


async def test_event_within_grace_cancels_replay(
    hass: HomeAssistant, learning_session: LearningSession, monkeypatch
) -> None:
    """If the learned event arrives within the grace window, replay is skipped."""
    import custom_components.openirblaster.learning as learning_module

    monkeypatch.setattr(learning_module, "_REPLAY_GRACE_SECONDS", 0.2)
    replay_mock = _install_replay_service_mock(hass)

    hass.services.async_register("switch", "turn_on", AsyncMock())
    hass.services.async_register("switch", "turn_off", AsyncMock())

    hass.states.async_set(_CAPTURE_MARKER_ENTITY_ID, "")
    await learning_session.async_start_learning()

    # Marker change schedules the wait task.
    hass.states.async_set(_CAPTURE_MARKER_ENTITY_ID, "2026-05-20T12:00:00+0000")
    await hass.async_block_till_done()

    # Event arrives well within the grace window.
    event = Event(
        EVENT_LEARNED,
        {
            ATTR_DEVICE_ID: "openirblaster-test123",
            ATTR_CARRIER_HZ: 38000,
            ATTR_PULSES_JSON: "[9000,-4500,560,-560]",
            ATTR_TIMESTAMP: "2026-05-20T12:00:00+0000",
        },
    )
    learning_session._async_handle_learned_event(event)
    await asyncio.sleep(0.6)  # well past the grace window

    assert learning_session.state == STATE_RECEIVED
    assert learning_session.pending_code is not None
    assert replay_mock.await_count == 0


async def test_marker_change_after_finalize_is_ignored(
    hass: HomeAssistant, learning_session: LearningSession, monkeypatch
) -> None:
    """A marker change that arrives after the capture is finalized is a no-op."""
    import custom_components.openirblaster.learning as learning_module

    monkeypatch.setattr(learning_module, "_REPLAY_GRACE_SECONDS", 0.1)
    replay_mock = _install_replay_service_mock(hass)

    hass.services.async_register("switch", "turn_on", AsyncMock())
    hass.services.async_register("switch", "turn_off", AsyncMock())

    hass.states.async_set(_CAPTURE_MARKER_ENTITY_ID, "")
    await learning_session.async_start_learning()

    # Event arrives first and finalizes.
    event = Event(
        EVENT_LEARNED,
        {
            ATTR_DEVICE_ID: "openirblaster-test123",
            ATTR_CARRIER_HZ: 38000,
            ATTR_PULSES_JSON: "[9000,-4500]",
            ATTR_TIMESTAMP: "2026-05-20T12:00:00+0000",
        },
    )
    learning_session._async_handle_learned_event(event)
    await asyncio.sleep(0.05)
    assert learning_session.state == STATE_RECEIVED

    # Now a stale marker change arrives (e.g., replay from a prior session).
    # The session has already moved out of ARMED, so the handler must ignore
    # it and never schedule a replay request.
    hass.states.async_set(_CAPTURE_MARKER_ENTITY_ID, "2026-05-20T12:00:00+0000")
    await hass.async_block_till_done()
    await asyncio.sleep(0.5)

    assert replay_mock.await_count == 0


@pytest.mark.parametrize("bad_state", ["", "unknown", "unavailable"])
async def test_marker_empty_or_unavailable_is_ignored(
    hass: HomeAssistant,
    learning_session: LearningSession,
    monkeypatch,
    bad_state: str,
) -> None:
    """Empty / unknown / unavailable marker states do not schedule a replay."""
    import custom_components.openirblaster.learning as learning_module

    monkeypatch.setattr(learning_module, "_REPLAY_GRACE_SECONDS", 0.1)
    replay_mock = _install_replay_service_mock(hass)

    hass.services.async_register("switch", "turn_on", AsyncMock())
    hass.services.async_register("switch", "turn_off", AsyncMock())

    hass.states.async_set(_CAPTURE_MARKER_ENTITY_ID, "seed")
    await learning_session.async_start_learning()

    hass.states.async_set(_CAPTURE_MARKER_ENTITY_ID, bad_state)
    await hass.async_block_till_done()
    await asyncio.sleep(0.5)

    assert learning_session.state == STATE_ARMED
    assert replay_mock.await_count == 0

    await learning_session.async_cleanup()


async def test_replay_skipped_when_send_service_unavailable(
    hass: HomeAssistant, learning_session: LearningSession, monkeypatch, caplog
) -> None:
    """If the send service is missing, we log and skip replay (no crash)."""
    import logging

    from unittest.mock import MagicMock

    from pytest_homeassistant_custom_component.common import MockConfigEntry

    import custom_components.openirblaster.learning as learning_module
    from custom_components.openirblaster.const import DOMAIN
    from custom_components.openirblaster.data import OpenIRBlasterData

    monkeypatch.setattr(learning_module, "_REPLAY_GRACE_SECONDS", 0.1)

    # Create the entry but leave esphome_service_name unset.
    entry = MockConfigEntry(domain=DOMAIN, entry_id="test_entry")
    entry.add_to_hass(hass)
    entry.runtime_data = OpenIRBlasterData(
        storage=MagicMock(),
        learning_session=MagicMock(),
        esphome_service_name=None,
    )

    hass.services.async_register("switch", "turn_on", AsyncMock())
    hass.services.async_register("switch", "turn_off", AsyncMock())
    hass.states.async_set(_CAPTURE_MARKER_ENTITY_ID, "")

    caplog.set_level(
        logging.ERROR, logger="custom_components.openirblaster.learning"
    )

    await learning_session.async_start_learning()
    hass.states.async_set(_CAPTURE_MARKER_ENTITY_ID, "2026-05-20T12:00:00+0000")
    await hass.async_block_till_done()
    await asyncio.sleep(0.5)

    assert any(
        "Cannot request replay" in rec.message for rec in caplog.records
    )
    assert learning_session.state == STATE_ARMED


async def test_clear_pending_cancels_pending_replay_task(
    hass: HomeAssistant, learning_session: LearningSession, monkeypatch
) -> None:
    """async_clear_pending cancels in-flight wait-then-replay tasks."""
    import custom_components.openirblaster.learning as learning_module

    monkeypatch.setattr(learning_module, "_REPLAY_GRACE_SECONDS", 0.5)
    replay_mock = _install_replay_service_mock(hass)

    hass.services.async_register("switch", "turn_on", AsyncMock())
    hass.services.async_register("switch", "turn_off", AsyncMock())

    hass.states.async_set(_CAPTURE_MARKER_ENTITY_ID, "")
    await learning_session.async_start_learning()

    # Trigger a marker change so a wait-then-replay task is scheduled.
    hass.states.async_set(_CAPTURE_MARKER_ENTITY_ID, "2026-05-20T12:00:00+0000")
    await hass.async_block_till_done()
    assert len(learning_session._pending_replay_tasks) == 1

    # User dismisses before grace elapses.
    await learning_session.async_clear_pending()
    await asyncio.sleep(1.0)  # past the original grace window

    assert learning_session._pending_replay_tasks == set()
    assert replay_mock.await_count == 0
    assert learning_session.state == STATE_IDLE


async def test_async_clear_pending_tears_down_listeners_and_timeout(
    hass: HomeAssistant, learning_session: LearningSession
) -> None:
    """async_clear_pending cancels the timeout and unsubscribes both listeners."""
    hass.services.async_register("switch", "turn_on", AsyncMock())
    hass.services.async_register("switch", "turn_off", AsyncMock())

    hass.states.async_set(_CAPTURE_MARKER_ENTITY_ID, "")
    await learning_session.async_start_learning()
    assert learning_session._timeout_unsub is not None
    assert learning_session._event_listener is not None
    assert learning_session._state_listener is not None

    # User dismisses without reaching STATE_RECEIVED
    await learning_session.async_clear_pending()

    # All subscriptions released, safe to start again
    assert learning_session._timeout_unsub is None
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
        unique_id="some-prefix-last_ir_capture_marker",
        suggested_object_id="custom_named_marker",
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
    assert resolved == "sensor.custom_named_marker"


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
            "Could not resolve capture marker text_sensor" in rec.message
            for rec in caplog.records
        )
    finally:
        await session.async_cleanup()


async def test_invalid_pulses_json_sets_finalized_flag_synchronously(
    hass: HomeAssistant, learning_session: LearningSession
) -> None:
    """A bad pulses_json must set `_capture_finalized = True` synchronously.

    Closes the race between the event path's validation failure and any
    concurrently-arriving replay event: if the flag were only flipped when
    the scheduled `_async_cancel` task finally ran, a replay event slipping
    through the `STATE_ARMED + not finalized` guard could commit a capture
    that the pending cancel would then clobber.

    We assert the flag is True *before* yielding to the event loop, which
    proves no interleaved handler can observe `_capture_finalized == False`.
    """
    hass.services.async_register("switch", "turn_on", AsyncMock())
    hass.services.async_register("switch", "turn_off", AsyncMock())

    hass.states.async_set(_CAPTURE_MARKER_ENTITY_ID, "")
    await learning_session.async_start_learning()
    assert learning_session._capture_finalized is False

    # Fire an event with garbage pulses_json. The handler is @callback (sync),
    # so by the time it returns the guard must have been flipped even though
    # _async_cancel is still a pending task.
    bad_event = Event(
        EVENT_LEARNED,
        {
            ATTR_DEVICE_ID: "openirblaster-test123",
            ATTR_CARRIER_HZ: 38000,
            ATTR_PULSES_JSON: "{not valid json",
            ATTR_TIMESTAMP: "2026-01-12T14:30:00-05:00",
        },
    )
    learning_session._async_handle_learned_event(bad_event)

    # Flag set synchronously, before any await has run the cancel task.
    assert learning_session._capture_finalized is True

    # A replay event arriving with valid data must still be ignored, because
    # the flag already blocks new captures from this session.
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

    # Drain the pending cancel task.
    await asyncio.sleep(0.1)

    # No valid code committed; session cancelled, not received.
    assert learning_session.pending_code is None
    assert learning_session.state == STATE_CANCELLED
