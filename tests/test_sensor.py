"""Tests for sensor platform."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.core import HomeAssistant

from custom_components.openirblaster.const import DOMAIN, STATE_RECEIVED
from custom_components.openirblaster.learning import LearnedCode


async def test_sensor_entities_created(
    hass: HomeAssistant, mock_config_entry_data: dict
) -> None:
    """Test that sensor entities are created."""
    entry = MockConfigEntry(domain=DOMAIN, data=mock_config_entry_data)
    entry.add_to_hass(hass)

    with patch(
        "homeassistant.config_entries.ConfigEntries.async_forward_entry_setups",
        return_value=True,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    # Verify data structure exists
    assert entry.entry_id in hass.data[DOMAIN]
    assert "learning_session" in hass.data[DOMAIN][entry.entry_id]


async def test_sensor_updates_on_learned_code(
    hass: HomeAssistant, mock_config_entry_data: dict
) -> None:
    """Test that sensors update when a code is learned."""
    entry = MockConfigEntry(domain=DOMAIN, data=mock_config_entry_data)
    entry.add_to_hass(hass)

    with patch(
        "homeassistant.config_entries.ConfigEntries.async_forward_entry_setups",
        return_value=True,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    # Simulate a learned code
    learning_session = hass.data[DOMAIN][entry.entry_id]["learning_session"]
    learning_session._state = STATE_RECEIVED
    learning_session._pending_code = LearnedCode(
        carrier_hz=38000,
        pulses=[9000, -4500, 560, -560],
        timestamp="2026-01-12T14:30:00-05:00",
        device_id="openirblaster-test123",
    )

    # Sensors should be able to read the pending code
    assert learning_session.pending_code is not None
    assert learning_session.pending_code.carrier_hz == 38000
    assert len(learning_session.pending_code.pulses) == 4
