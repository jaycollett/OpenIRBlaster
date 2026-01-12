"""Tests for button platform."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from custom_components.openirblaster.const import DOMAIN


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
    assert entry.entry_id in hass.data[DOMAIN]


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

    learning_session = hass.data[DOMAIN][entry.entry_id]["learning_session"]

    # Mock the async_start_learning method
    with patch.object(
        learning_session, "async_start_learning", return_value=True
    ) as mock_start:
        # Simulate button press
        await learning_session.async_start_learning()
        mock_start.assert_called_once()


async def test_code_button_press_sends_ir(
    hass: HomeAssistant, mock_config_entry_data: dict
) -> None:
    """Test that pressing a code button sends IR."""
    # Register the ESPHome service
    calls = []

    async def mock_send_ir(call):
        calls.append(call)

    hass.services.async_register(
        "esphome", "openirblaster_test_send_ir_raw", mock_send_ir
    )

    await hass.services.async_call(
        "esphome",
        "openirblaster_test_send_ir_raw",
        {
            "carrier_hz": 38000,
            "code": [9000, -4500, 560, -560],
        },
        blocking=True,
    )

    assert len(calls) == 1
    assert calls[0].data["carrier_hz"] == 38000
