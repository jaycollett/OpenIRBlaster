"""Tests for services module."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er

from custom_components.openirblaster.const import (
    ATTR_CARRIER_HZ,
    ATTR_CODE_ID,
    ATTR_PULSES,
    DOMAIN,
    SERVICE_DELETE_CODE,
    SERVICE_LEARN_START,
    SERVICE_RENAME_CODE,
    SERVICE_SAVE_PENDING,
    SERVICE_SEND_CODE,
)
from custom_components.openirblaster.learning import LearnedCode
from custom_components.openirblaster.services import async_setup_services


async def test_setup_services(hass: HomeAssistant) -> None:
    """Test that services are registered."""
    await async_setup_services(hass)

    # Verify services are registered
    assert hass.services.has_service(DOMAIN, SERVICE_LEARN_START)
    assert hass.services.has_service(DOMAIN, SERVICE_SEND_CODE)
    assert hass.services.has_service(DOMAIN, SERVICE_DELETE_CODE)
    assert hass.services.has_service(DOMAIN, SERVICE_RENAME_CODE)
    assert hass.services.has_service(DOMAIN, SERVICE_SAVE_PENDING)


async def test_service_rejects_unknown_entry(hass: HomeAssistant) -> None:
    """A config_entry_id that does not exist raises config_entry_not_found."""
    await async_setup_services(hass)

    with pytest.raises(ServiceValidationError) as excinfo:
        await hass.services.async_call(
            DOMAIN,
            SERVICE_LEARN_START,
            {"config_entry_id": "does_not_exist"},
            blocking=True,
        )

    assert excinfo.value.translation_key == "config_entry_not_found"


async def test_service_rejects_not_loaded_entry(
    hass: HomeAssistant, mock_config_entry_data: dict
) -> None:
    """An entry that exists but is not loaded raises config_entry_not_loaded.

    Services are registered in async_setup, so they exist even when no
    entry is loaded; the handlers must verify the entry state themselves.
    """
    await async_setup_services(hass)

    entry = MockConfigEntry(domain=DOMAIN, data=mock_config_entry_data)
    entry.add_to_hass(hass)  # added, never set up -> NOT_LOADED

    with pytest.raises(ServiceValidationError) as excinfo:
        await hass.services.async_call(
            DOMAIN,
            SERVICE_LEARN_START,
            {"config_entry_id": entry.entry_id},
            blocking=True,
        )

    assert excinfo.value.translation_key == "config_entry_not_loaded"


async def test_learn_start_service(
    hass: HomeAssistant, mock_config_entry_data: dict
) -> None:
    """Test learn_start service."""
    entry = MockConfigEntry(domain=DOMAIN, data=mock_config_entry_data)
    entry.add_to_hass(hass)

    with patch(
        "homeassistant.config_entries.ConfigEntries.async_forward_entry_setups",
        return_value=True,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    learning_session = entry.runtime_data.learning_session

    with patch.object(
        learning_session, "async_start_learning", return_value=True
    ) as mock_start:
        await hass.services.async_call(
            DOMAIN,
            SERVICE_LEARN_START,
            {"config_entry_id": entry.entry_id, "timeout": 10},
            blocking=True,
        )

        # The override is passed per-call; the session default is untouched
        mock_start.assert_awaited_once_with(timeout=10)
        assert learning_session.timeout == 30


async def test_learn_start_timeout_override_is_per_session(
    hass: HomeAssistant, mock_config_entry_data: dict
) -> None:
    """A learn_start timeout override must not stick for later sessions.

    The handler used to assign ``learning_session.timeout = timeout``,
    permanently mutating the default. After a learn_start with timeout 120,
    a subsequent button-initiated session (no override) must schedule the
    default 30 seconds again.
    """
    import custom_components.openirblaster.learning as learning_module

    entry = MockConfigEntry(domain=DOMAIN, data=mock_config_entry_data)
    entry.add_to_hass(hass)

    with patch(
        "homeassistant.config_entries.ConfigEntries.async_forward_entry_setups",
        return_value=True,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    learning_session = entry.runtime_data.learning_session

    hass.services.async_register("switch", "turn_on", AsyncMock())
    hass.services.async_register("switch", "turn_off", AsyncMock())

    delays: list[float] = []
    real_async_call_later = learning_module.async_call_later

    def spy_async_call_later(hass_, delay, action):
        delays.append(delay)
        return real_async_call_later(hass_, delay, action)

    with patch.object(
        learning_module, "async_call_later", side_effect=spy_async_call_later
    ):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_LEARN_START,
            {"config_entry_id": entry.entry_id, "timeout": 120},
            blocking=True,
        )
        assert delays == [120]
        assert learning_session.timeout == 30  # default not mutated

        await learning_session.async_clear_pending()

        # A subsequent session without an override uses the default again
        assert await learning_session.async_start_learning() is True
        assert delays == [120, 30]

    await learning_session.async_cleanup()


async def test_send_code_service(
    hass: HomeAssistant, mock_config_entry_data: dict, mock_stored_code: dict
) -> None:
    """Test send_code service."""
    # Register ESPHome service BEFORE integration setup (so discovery finds it)
    esphome_calls = []

    async def mock_esphome_service(call):
        esphome_calls.append(call)

    hass.services.async_register(
        "esphome", "openirblaster_test_send_ir_raw", mock_esphome_service
    )

    entry = MockConfigEntry(domain=DOMAIN, data=mock_config_entry_data)
    entry.add_to_hass(hass)

    with patch(
        "homeassistant.config_entries.ConfigEntries.async_forward_entry_setups",
        return_value=True,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    # Add a code to storage
    storage = entry.runtime_data.storage
    await storage.async_add_code(
        name="Test Code",
        carrier_hz=38000,
        pulses=[9000, -4500],
    )

    await hass.services.async_call(
        DOMAIN,
        SERVICE_SEND_CODE,
        {
            "config_entry_id": entry.entry_id,
            ATTR_CODE_ID: "test_code",
        },
        blocking=True,
    )

    # Verify ESPHome service was called
    assert len(esphome_calls) == 1
    assert esphome_calls[0].data["carrier_hz"] == 38000
    assert esphome_calls[0].data["code"] == [9000, -4500]


async def test_delete_code_service(
    hass: HomeAssistant, mock_config_entry_data: dict
) -> None:
    """Test delete_code service."""
    entry = MockConfigEntry(domain=DOMAIN, data=mock_config_entry_data)
    entry.add_to_hass(hass)

    with patch(
        "homeassistant.config_entries.ConfigEntries.async_forward_entry_setups",
        return_value=True,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    # Add a code to storage
    storage = entry.runtime_data.storage
    await storage.async_add_code(
        name="Test Code",
        carrier_hz=38000,
        pulses=[9000, -4500],
    )

    assert len(storage.get_codes()) == 1

    with patch(
        "homeassistant.config_entries.ConfigEntries.async_reload"
    ) as mock_reload:
        await hass.services.async_call(
            DOMAIN,
            SERVICE_DELETE_CODE,
            {
                "config_entry_id": entry.entry_id,
                ATTR_CODE_ID: "test_code",
            },
            blocking=True,
        )

    # Verify code was deleted without an entry reload
    assert len(storage.get_codes()) == 0
    mock_reload.assert_not_called()


async def test_rename_code_service(
    hass: HomeAssistant, mock_config_entry_data: dict
) -> None:
    """Test rename_code service."""
    entry = MockConfigEntry(domain=DOMAIN, data=mock_config_entry_data)
    entry.add_to_hass(hass)

    with patch(
        "homeassistant.config_entries.ConfigEntries.async_forward_entry_setups",
        return_value=True,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    # Add a code to storage
    storage = entry.runtime_data.storage
    await storage.async_add_code(
        name="Old Name",
        carrier_hz=38000,
        pulses=[9000, -4500],
    )

    with patch(
        "homeassistant.config_entries.ConfigEntries.async_reload"
    ) as mock_reload:
        await hass.services.async_call(
            DOMAIN,
            SERVICE_RENAME_CODE,
            {
                "config_entry_id": entry.entry_id,
                ATTR_CODE_ID: "old_name",
                "new_name": "New Name",
            },
            blocking=True,
        )

    # Verify code was renamed without an entry reload
    code = storage.get_code("old_name")
    assert code is not None
    assert code["name"] == "New Name"
    mock_reload.assert_not_called()


async def test_delete_code_service_removes_registry_entry(
    hass: HomeAssistant, mock_config_entry_data: dict
) -> None:
    """Service-based delete must clean the code button out of the registry.

    The options-flow delete path already removed registry entries; the
    service path used to skip it, leaving an orphaned "no longer provided"
    button entity behind after the reload.
    """
    entry = MockConfigEntry(domain=DOMAIN, data=mock_config_entry_data)
    entry.add_to_hass(hass)

    with patch(
        "homeassistant.config_entries.ConfigEntries.async_forward_entry_setups",
        return_value=True,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    storage = entry.runtime_data.storage
    await storage.async_add_code(
        name="Test Code",
        carrier_hz=38000,
        pulses=[9000, -4500],
    )

    # Register the code's button entity as the button platform would
    registry = er.async_get(hass)
    unique_id = f"{entry.entry_id}_test_code"
    registry.async_get_or_create(
        domain="button",
        platform=DOMAIN,
        unique_id=unique_id,
        config_entry=entry,
    )
    assert registry.async_get_entity_id("button", DOMAIN, unique_id) is not None

    with patch(
        "homeassistant.config_entries.ConfigEntries.async_reload"
    ) as mock_reload:
        await hass.services.async_call(
            DOMAIN,
            SERVICE_DELETE_CODE,
            {
                "config_entry_id": entry.entry_id,
                ATTR_CODE_ID: "test_code",
            },
            blocking=True,
        )

    assert len(storage.get_codes()) == 0
    # The registry entry is gone, not orphaned, and no reload happened
    assert registry.async_get_entity_id("button", DOMAIN, unique_id) is None
    mock_reload.assert_not_called()


async def test_save_pending_rejects_duplicate_name(
    hass: HomeAssistant, mock_config_entry_data: dict
) -> None:
    """save_pending must reject a name that already exists in storage."""
    entry = MockConfigEntry(domain=DOMAIN, data=mock_config_entry_data)
    entry.add_to_hass(hass)

    with patch(
        "homeassistant.config_entries.ConfigEntries.async_forward_entry_setups",
        return_value=True,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    storage = entry.runtime_data.storage
    await storage.async_add_code(
        name="TV Power",
        carrier_hz=38000,
        pulses=[9000, -4500],
    )

    learning_session = entry.runtime_data.learning_session
    learning_session._pending_code = LearnedCode(
        carrier_hz=38000,
        pulses=[9000, -4500, 560, -560],
        timestamp="2026-01-12T14:30:00-05:00",
        device_id="openirblaster-test123",
    )

    with pytest.raises(ServiceValidationError) as excinfo:
        await hass.services.async_call(
            DOMAIN,
            SERVICE_SAVE_PENDING,
            {
                "config_entry_id": entry.entry_id,
                "name": "TV Power",
            },
            blocking=True,
        )

    assert excinfo.value.translation_key == "name_exists"
    # The pending code is untouched and nothing new was stored
    assert learning_session.pending_code is not None
    assert len(storage.get_codes()) == 1


# ---------------------------------------------------------------------------
# supports_response: learn_start / send_code / save_pending optionally return
# structured data when called with return_response=True.
# ---------------------------------------------------------------------------


async def _async_setup_entry_for_services(
    hass: HomeAssistant, mock_config_entry_data: dict
) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, data=mock_config_entry_data)
    entry.add_to_hass(hass)
    with patch(
        "homeassistant.config_entries.ConfigEntries.async_forward_entry_setups",
        return_value=True,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


async def test_learn_start_response_received(
    hass: HomeAssistant, mock_config_entry_data: dict
) -> None:
    """learn_start with return_response waits for and returns the capture."""
    import asyncio

    from homeassistant.core import Event

    from custom_components.openirblaster.const import (
        ATTR_CARRIER_HZ as EVT_CARRIER,
        ATTR_DEVICE_ID,
        ATTR_PULSES_JSON,
        ATTR_TIMESTAMP,
        EVENT_LEARNED,
        STATE_ARMED,
    )

    entry = await _async_setup_entry_for_services(hass, mock_config_entry_data)
    session = entry.runtime_data.learning_session

    hass.services.async_register("switch", "turn_on", AsyncMock())
    hass.services.async_register("switch", "turn_off", AsyncMock())

    task = hass.async_create_task(
        hass.services.async_call(
            DOMAIN,
            SERVICE_LEARN_START,
            {"config_entry_id": entry.entry_id, "timeout": 30},
            blocking=True,
            return_response=True,
        )
    )

    # Wait for the session to arm, then inject the capture
    for _ in range(100):
        if session.state == STATE_ARMED:
            break
        await asyncio.sleep(0.01)
    assert session.state == STATE_ARMED

    session._async_handle_learned_event(
        Event(
            EVENT_LEARNED,
            {
                ATTR_DEVICE_ID: "openirblaster-test123",
                EVT_CARRIER: 38000,
                ATTR_PULSES_JSON: "[9000,-4500,560,-560]",
                ATTR_TIMESTAMP: "2026-01-12T14:30:00-05:00",
            },
        )
    )

    response = await task
    assert response == {
        "status": "received",
        "carrier_hz": 38000,
        "pulse_count": 4,
        "timestamp": "2026-01-12T14:30:00-05:00",
    }
    # The outcome callback was removed again
    assert len(session._callbacks) == 0

    await session.async_cleanup()


async def test_learn_start_response_timeout(
    hass: HomeAssistant, mock_config_entry_data: dict
) -> None:
    """learn_start with return_response reports a session timeout."""
    entry = await _async_setup_entry_for_services(hass, mock_config_entry_data)
    session = entry.runtime_data.learning_session

    hass.services.async_register("switch", "turn_on", AsyncMock())
    hass.services.async_register("switch", "turn_off", AsyncMock())

    response = await hass.services.async_call(
        DOMAIN,
        SERVICE_LEARN_START,
        {"config_entry_id": entry.entry_id, "timeout": 1},
        blocking=True,
        return_response=True,
    )

    assert response == {"status": "timeout"}
    assert len(session._callbacks) == 0


async def test_learn_start_without_response_unchanged(
    hass: HomeAssistant, mock_config_entry_data: dict
) -> None:
    """Without return_response, learn_start stays fire-and-forget."""
    from custom_components.openirblaster.const import STATE_ARMED

    entry = await _async_setup_entry_for_services(hass, mock_config_entry_data)
    session = entry.runtime_data.learning_session

    hass.services.async_register("switch", "turn_on", AsyncMock())
    hass.services.async_register("switch", "turn_off", AsyncMock())

    response = await hass.services.async_call(
        DOMAIN,
        SERVICE_LEARN_START,
        {"config_entry_id": entry.entry_id, "timeout": 30},
        blocking=True,
    )

    # Returns immediately with the session armed and no payload
    assert response is None
    assert session.state == STATE_ARMED
    assert len(session._callbacks) == 0

    await session.async_cleanup()


async def test_send_code_response(
    hass: HomeAssistant, mock_config_entry_data: dict
) -> None:
    """send_code with return_response returns the sent code's identity."""
    esphome_calls = []

    async def mock_esphome_service(call):
        esphome_calls.append(call)

    hass.services.async_register(
        "esphome", "openirblaster_test_send_ir_raw", mock_esphome_service
    )

    entry = await _async_setup_entry_for_services(hass, mock_config_entry_data)

    storage = entry.runtime_data.storage
    await storage.async_add_code(
        name="Test Code",
        carrier_hz=38000,
        pulses=[9000, -4500],
    )

    response = await hass.services.async_call(
        DOMAIN,
        SERVICE_SEND_CODE,
        {"config_entry_id": entry.entry_id, ATTR_CODE_ID: "test_code"},
        blocking=True,
        return_response=True,
    )

    assert len(esphome_calls) == 1
    assert response == {
        "code_id": "test_code",
        "name": "Test Code",
        "carrier_hz": 38000,
        "pulse_count": 2,
        "sent": True,
    }


async def test_save_pending_response(
    hass: HomeAssistant, mock_config_entry_data: dict
) -> None:
    """save_pending with return_response returns the saved code."""
    entry = await _async_setup_entry_for_services(hass, mock_config_entry_data)

    session = entry.runtime_data.learning_session
    session._pending_code = LearnedCode(
        carrier_hz=40000,
        pulses=[9000, -4500, 560],
        timestamp="2026-01-12T14:30:00-05:00",
        device_id="openirblaster-test123",
    )

    response = await hass.services.async_call(
        DOMAIN,
        SERVICE_SAVE_PENDING,
        {"config_entry_id": entry.entry_id, "name": "TV Power"},
        blocking=True,
        return_response=True,
    )

    assert response == {
        "code_id": "tv_power",
        "name": "TV Power",
        "carrier_hz": 40000,
        "pulse_count": 3,
    }
    # Saved for real, pending cleared
    storage = entry.runtime_data.storage
    assert storage.get_code("tv_power") is not None
    assert session.pending_code is None


# ---------------------------------------------------------------------------
# QA batch: learn_cancel service and delete_code cross-entry ambiguity.
# ---------------------------------------------------------------------------


async def test_learn_cancel_service_cancels_armed_session(
    hass: HomeAssistant, mock_config_entry_data: dict
) -> None:
    """learn_cancel on an ARMED session turns the switch off and idles."""
    from custom_components.openirblaster.const import (
        SERVICE_LEARN_CANCEL,
        STATE_ARMED,
        STATE_IDLE,
    )

    entry = await _async_setup_entry_for_services(hass, mock_config_entry_data)
    session = entry.runtime_data.learning_session

    turn_off_calls = []

    async def mock_turn_off(call):
        turn_off_calls.append(call)

    hass.services.async_register("switch", "turn_on", AsyncMock())
    hass.services.async_register("switch", "turn_off", mock_turn_off)

    assert await session.async_start_learning() is True
    assert session.state == STATE_ARMED

    await hass.services.async_call(
        DOMAIN,
        SERVICE_LEARN_CANCEL,
        {"config_entry_id": entry.entry_id},
        blocking=True,
    )

    assert session.state == STATE_IDLE
    assert len(turn_off_calls) == 1
    assert session._event_listener is None
    assert session._timeout_unsub is None


async def test_learn_cancel_rejects_unsaved_pending_by_default(
    hass: HomeAssistant, mock_config_entry_data: dict
) -> None:
    """learn_cancel refuses to drop a pending code unless told to."""
    from custom_components.openirblaster.const import (
        SERVICE_LEARN_CANCEL,
        STATE_RECEIVED,
    )

    entry = await _async_setup_entry_for_services(hass, mock_config_entry_data)
    session = entry.runtime_data.learning_session
    session._state = STATE_RECEIVED
    session._pending_code = LearnedCode(
        carrier_hz=38000,
        pulses=[9000, -4500],
        timestamp="2026-01-12T14:30:00-05:00",
        device_id="openirblaster-test123",
    )

    with pytest.raises(ServiceValidationError) as excinfo:
        await hass.services.async_call(
            DOMAIN,
            SERVICE_LEARN_CANCEL,
            {"config_entry_id": entry.entry_id},
            blocking=True,
        )

    assert excinfo.value.translation_key == "pending_code_unsaved"
    assert session.pending_code is not None


async def test_learn_cancel_discards_pending_when_asked(
    hass: HomeAssistant, mock_config_entry_data: dict
) -> None:
    """learn_cancel with discard_pending true clears the pending code."""
    from custom_components.openirblaster.const import (
        SERVICE_LEARN_CANCEL,
        STATE_IDLE,
        STATE_RECEIVED,
    )

    entry = await _async_setup_entry_for_services(hass, mock_config_entry_data)
    session = entry.runtime_data.learning_session
    session._state = STATE_RECEIVED
    session._pending_code = LearnedCode(
        carrier_hz=38000,
        pulses=[9000, -4500],
        timestamp="2026-01-12T14:30:00-05:00",
        device_id="openirblaster-test123",
    )

    await hass.services.async_call(
        DOMAIN,
        SERVICE_LEARN_CANCEL,
        {"config_entry_id": entry.entry_id, "discard_pending": True},
        blocking=True,
    )

    assert session.state == STATE_IDLE
    assert session.pending_code is None


async def test_delete_code_ambiguous_across_entries_rejected(
    hass: HomeAssistant, mock_config_entry_data: dict
) -> None:
    """Auto-detect delete with the code on two entries must not guess."""
    entry_one = await _async_setup_entry_for_services(
        hass, mock_config_entry_data
    )
    entry_two = MockConfigEntry(domain=DOMAIN, data=dict(mock_config_entry_data))
    entry_two.add_to_hass(hass)
    with patch(
        "homeassistant.config_entries.ConfigEntries.async_forward_entry_setups",
        return_value=True,
    ):
        await hass.config_entries.async_setup(entry_two.entry_id)
        await hass.async_block_till_done()

    # The same code name (and therefore code_id) on both blasters
    for entry in (entry_one, entry_two):
        await entry.runtime_data.storage.async_add_code(
            name="TV Power", carrier_hz=38000, pulses=[9000, -4500]
        )

    with pytest.raises(ServiceValidationError) as excinfo:
        await hass.services.async_call(
            DOMAIN,
            SERVICE_DELETE_CODE,
            {ATTR_CODE_ID: "tv_power"},
            blocking=True,
        )

    assert excinfo.value.translation_key == "code_id_ambiguous"
    # Nothing was deleted from either entry
    assert entry_one.runtime_data.storage.get_code("tv_power") is not None
    assert entry_two.runtime_data.storage.get_code("tv_power") is not None


async def test_cancel_vs_capture_race_must_not_lose_code(
    hass: HomeAssistant, mock_config_entry_data: dict
) -> None:
    """learn_cancel racing a committed capture must not destroy the code.

    Window: the capture commits (_capture_finalized set) but the finalize
    task is suspended awaiting the network switch turn-off, so the session
    still reads ARMED. A learn_cancel WITHOUT discard_pending arriving in
    that window must be rejected (pending_code_unsaved), and the captured
    code must survive to RECEIVED.
    """
    import asyncio

    from custom_components.openirblaster.const import (
        EVENT_LEARNED,
        SERVICE_LEARN_CANCEL,
        STATE_ARMED,
        STATE_RECEIVED,
    )

    entry = await _async_setup_entry_for_services(hass, mock_config_entry_data)
    session = entry.runtime_data.learning_session

    # Gate switch.turn_off so the finalize task suspends mid-flight,
    # exactly like a real network call to the ESPHome device.
    gate = asyncio.Event()

    async def slow_turn_off(call):
        await gate.wait()

    hass.services.async_register("switch", "turn_on", AsyncMock())
    hass.services.async_register("switch", "turn_off", slow_turn_off)

    assert await session.async_start_learning() is True
    assert session.state == STATE_ARMED

    # Commit the capture; finalize eagerly runs until the gated turn_off,
    # leaving the session committed (_capture_finalized) but still ARMED.
    hass.bus.async_fire(
        EVENT_LEARNED,
        {
            "device_id": "openirblaster-test123",
            "carrier_hz": 38000,
            "pulses_json": "[9000,-4500,560,-560,560,-1680,560,-560]",
            "timestamp": "2026-01-12T14:30:00-05:00",
            "rssi": -45,
        },
    )
    assert session._capture_finalized is True
    assert session.state == STATE_ARMED

    # learn_cancel in the race window, WITHOUT discard_pending
    cancel_task = hass.async_create_task(
        hass.services.async_call(
            DOMAIN,
            SERVICE_LEARN_CANCEL,
            {"config_entry_id": entry.entry_id},
            blocking=True,
        )
    )
    await asyncio.sleep(0)
    gate.set()

    with pytest.raises(ServiceValidationError) as excinfo:
        await cancel_task
    assert excinfo.value.translation_key == "pending_code_unsaved"

    # The captured code survived and the session finalizes normally
    assert session.pending_code is not None
    await hass.async_block_till_done()
    assert session.state == STATE_RECEIVED
    assert session.pending_code is not None
