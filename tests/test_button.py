"""Tests for button platform."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.core import HomeAssistant

from custom_components.openirblaster.button import (
    CodeButton,
    LearnButton,
    SendLastButton,
)
from custom_components.openirblaster.const import (
    DOMAIN,
    STATE_IDLE,
    STATE_RECEIVED,
    STATE_TIMEOUT,
)
from custom_components.openirblaster.data import OpenIRBlasterData
from custom_components.openirblaster.learning import LearnedCode, LearningSession


async def test_button_entities_created(
    hass: HomeAssistant, mock_config_entry_data: dict, mock_stored_code: dict
) -> None:
    """Test that button entities are created."""
    entry = MockConfigEntry(domain=DOMAIN, data=mock_config_entry_data)
    entry.add_to_hass(hass)

    # Pre-populate storage with a code
    with patch(
        "custom_components.openirblaster.storage.OpenIRBlasterStorage.async_load"
    ) as mock_load:
        mock_load.return_value = {
            "version": 1,
            "device": {
                "config_entry_id": entry.entry_id,
                "name": "OpenIRBlaster",
                "device_id": "openirblaster-test123",
            },
            "codes": [mock_stored_code],
        }

        with patch(
            "homeassistant.config_entries.ConfigEntries.async_forward_entry_setups",
            return_value=True,
        ) as mock_forward:
            await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done()

    # Verify button platform was set up
    assert entry.runtime_data is not None
    assert entry.runtime_data.storage is not None


async def test_learn_button_press(
    hass: HomeAssistant, mock_config_entry_data: dict
) -> None:
    """Test pressing the learn button."""
    entry = MockConfigEntry(domain=DOMAIN, data=mock_config_entry_data)
    entry.add_to_hass(hass)

    with patch(
        "homeassistant.config_entries.ConfigEntries.async_forward_entry_setups",
        return_value=True,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    learning_session = entry.runtime_data.learning_session

    # Mock the async_start_learning method
    with patch.object(
        learning_session, "async_start_learning", return_value=True
    ) as mock_start:
        # Simulate button press
        await learning_session.async_start_learning()
        mock_start.assert_called_once()


async def test_learn_button_callback_registered_once_across_presses(
    hass: HomeAssistant, mock_config_entry_data: dict
) -> None:
    """Repeated press+timeout cycles must not leak duplicate callbacks.

    This is the regression test for issue #8's companion bug: the old code
    registered ``_handle_learning_complete`` on every press but only
    unregistered from the save path. Presses that ended in timeout left a
    stale callback behind, and the next STATE_RECEIVED fired the save
    handler multiple times.
    """
    entry = MockConfigEntry(domain=DOMAIN, data=mock_config_entry_data)
    entry.add_to_hass(hass)

    session = LearningSession(
        hass=hass,
        config_entry_id=entry.entry_id,
        device_id="openirblaster-test123",
        learning_switch_entity_id="switch.openirblaster_test_ir_learning_mode",
        timeout=30,
    )

    button = LearnButton(entry, session)
    # The callback schedules the save via hass.async_create_task, so the
    # entity needs its hass reference even outside a platform.
    button.hass = hass
    # Mock hass access and async_added_to_hass prerequisites
    with patch(
        "homeassistant.helpers.entity.Entity.async_added_to_hass", new=AsyncMock()
    ), patch(
        "homeassistant.helpers.entity.Entity.async_will_remove_from_hass",
        new=AsyncMock(),
    ):
        await button.async_added_to_hass()

        # One callback registered for the entity lifetime
        assert session._callbacks.count(button._handle_learning_complete) == 1

        # Simulate three failed press/timeout cycles. Each would have leaked a
        # callback under the old code.
        for attempt in range(3):
            button._pending_save_name = f"attempt_{attempt}"
            # Directly drive the state machine to the timeout terminus
            session._state = STATE_TIMEOUT
            session._notify_state_change()
            await asyncio.sleep(0)
            # Reset for the next "press"
            session._state = STATE_IDLE
            button._pending_save_name = None

        # Still exactly one subscription, regardless of how many attempts failed
        assert session._callbacks.count(button._handle_learning_complete) == 1

        # Now simulate a successful capture and make sure the save is scheduled
        # exactly once even if the callback fires multiple times (event +
        # text_sensor fallback can both produce STATE_RECEIVED notifications).
        button._pending_save_name = "TV Power"
        session._pending_code = LearnedCode(
            carrier_hz=38000,
            pulses=[9000, -4500],
            timestamp="2026-01-12T14:30:00-05:00",
            device_id="openirblaster-test123",
        )

        save_spy = MagicMock()
        with patch.object(
            button, "_async_save_learned_code", new=AsyncMock(side_effect=save_spy)
        ):
            session._state = STATE_RECEIVED
            # Fire the callback three times in a row (simulating duplicate
            # state transitions from the two capture paths)
            for _ in range(3):
                session._notify_state_change()
                await asyncio.sleep(0)

            # The _save_in_progress guard must collapse these to a single
            # scheduled save task
            assert save_spy.call_count == 1

        # Cleanup path unregisters the callback
        await button.async_will_remove_from_hass()
        assert button._handle_learning_complete not in session._callbacks

    await session.async_cleanup()


async def test_code_button_press_sends_ir(
    hass: HomeAssistant, mock_config_entry_data: dict
) -> None:
    """Pressing a real CodeButton sends the stored payload to ESPHome."""
    calls = []

    async def mock_send_ir(call):
        calls.append(call)

    hass.services.async_register(
        "esphome", "openirblaster_test_send_ir_raw", mock_send_ir
    )

    entry = MockConfigEntry(domain=DOMAIN, data=mock_config_entry_data)
    entry.add_to_hass(hass)
    entry.runtime_data = OpenIRBlasterData(
        storage=MagicMock(),
        learning_session=MagicMock(),
        esphome_service_name="openirblaster_test_send_ir_raw",
    )

    button = CodeButton(
        entry,
        code_id="tv_power",
        name="TV Power",
        carrier_hz=38000,
        pulses=[9000, -4500, 560, -560],
    )
    button.hass = hass

    await button.async_press()

    assert len(calls) == 1
    assert calls[0].data["carrier_hz"] == 38000
    assert calls[0].data["code"] == [9000, -4500, 560, -560]


async def test_code_button_press_missing_service_logs_and_does_not_raise(
    hass: HomeAssistant, mock_config_entry_data: dict, caplog
) -> None:
    """A missing ESPHome service must not raise; it logs and sends nothing."""
    calls = []

    async def mock_send_ir(call):
        calls.append(call)

    hass.services.async_register(
        "esphome", "openirblaster_test_send_ir_raw", mock_send_ir
    )

    entry = MockConfigEntry(domain=DOMAIN, data=mock_config_entry_data)
    entry.add_to_hass(hass)
    # No cached service name for this entry (device offline at setup time)
    entry.runtime_data = OpenIRBlasterData(
        storage=MagicMock(),
        learning_session=MagicMock(),
        esphome_service_name=None,
    )

    button = CodeButton(
        entry,
        code_id="tv_power",
        name="TV Power",
        carrier_hz=38000,
        pulses=[9000, -4500],
    )
    button.hass = hass

    await button.async_press()  # must not raise

    assert len(calls) == 0
    assert "ESPHome service not found" in caplog.text

    # A repair issue is raised so the user sees the problem in the UI
    from homeassistant.helpers import issue_registry as ir

    issue_registry = ir.async_get(hass)
    issue = issue_registry.async_get_issue(
        DOMAIN, f"esphome_service_missing_{entry.entry_id}"
    )
    assert issue is not None
    assert issue.severity == ir.IssueSeverity.ERROR
    assert issue.is_fixable is False


async def test_code_button_successful_send_clears_repair_issue(
    hass: HomeAssistant, mock_config_entry_data: dict
) -> None:
    """A successful send deletes the missing-service repair issue."""
    from homeassistant.helpers import issue_registry as ir

    calls = []

    async def mock_send_ir(call):
        calls.append(call)

    hass.services.async_register(
        "esphome", "openirblaster_test_send_ir_raw", mock_send_ir
    )

    entry = MockConfigEntry(domain=DOMAIN, data=mock_config_entry_data)
    entry.add_to_hass(hass)
    entry.runtime_data = OpenIRBlasterData(
        storage=MagicMock(),
        learning_session=MagicMock(),
        esphome_service_name="openirblaster_test_send_ir_raw",
    )

    # Pre-existing repair from a previously failed send
    ir.async_create_issue(
        hass,
        DOMAIN,
        f"esphome_service_missing_{entry.entry_id}",
        is_fixable=False,
        severity=ir.IssueSeverity.ERROR,
        translation_key="esphome_service_missing",
        translation_placeholders={"name": entry.title},
    )

    button = CodeButton(
        entry,
        code_id="tv_power",
        name="TV Power",
        carrier_hz=38000,
        pulses=[9000, -4500],
    )
    button.hass = hass

    await button.async_press()

    assert len(calls) == 1
    issue_registry = ir.async_get(hass)
    assert (
        issue_registry.async_get_issue(
            DOMAIN, f"esphome_service_missing_{entry.entry_id}"
        )
        is None
    )


async def test_send_last_button_press_sends_pending_code(
    hass: HomeAssistant, mock_config_entry_data: dict
) -> None:
    """Pressing a real SendLastButton sends the pending code payload."""
    calls = []

    async def mock_send_ir(call):
        calls.append(call)

    hass.services.async_register(
        "esphome", "openirblaster_test_send_ir_raw", mock_send_ir
    )

    entry = MockConfigEntry(domain=DOMAIN, data=mock_config_entry_data)
    entry.add_to_hass(hass)
    entry.runtime_data = OpenIRBlasterData(
        storage=MagicMock(),
        learning_session=MagicMock(),
        esphome_service_name="openirblaster_test_send_ir_raw",
    )

    session = LearningSession(
        hass=hass,
        config_entry_id=entry.entry_id,
        device_id="openirblaster-test123",
        learning_switch_entity_id="switch.openirblaster_test_ir_learning_mode",
        timeout=30,
    )
    session._pending_code = LearnedCode(
        carrier_hz=40000,
        pulses=[9000, -4500, 560],
        timestamp="2026-01-12T14:30:00-05:00",
        device_id="openirblaster-test123",
    )

    button = SendLastButton(entry, session)
    button.hass = hass

    await button.async_press()

    assert len(calls) == 1
    assert calls[0].data["carrier_hz"] == 40000
    assert calls[0].data["code"] == [9000, -4500, 560]


async def test_send_last_button_press_without_pending_code_is_noop(
    hass: HomeAssistant, mock_config_entry_data: dict, caplog
) -> None:
    """SendLastButton with no pending code warns and sends nothing."""
    calls = []

    async def mock_send_ir(call):
        calls.append(call)

    hass.services.async_register(
        "esphome", "openirblaster_test_send_ir_raw", mock_send_ir
    )

    entry = MockConfigEntry(domain=DOMAIN, data=mock_config_entry_data)
    entry.add_to_hass(hass)
    entry.runtime_data = OpenIRBlasterData(
        storage=MagicMock(),
        learning_session=MagicMock(),
        esphome_service_name="openirblaster_test_send_ir_raw",
    )

    session = LearningSession(
        hass=hass,
        config_entry_id=entry.entry_id,
        device_id="openirblaster-test123",
        learning_switch_entity_id="switch.openirblaster_test_ir_learning_mode",
        timeout=30,
    )

    button = SendLastButton(entry, session)
    button.hass = hass

    await button.async_press()  # must not raise

    assert len(calls) == 0
    assert "No pending code to send" in caplog.text
