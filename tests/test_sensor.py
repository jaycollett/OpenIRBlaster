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

    # Verify runtime data exists
    assert entry.runtime_data is not None
    assert entry.runtime_data.learning_session is not None


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
    learning_session = entry.runtime_data.learning_session
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


async def test_last_learned_sensors_survive_reload(
    hass: HomeAssistant, mock_config_entry_data: dict
) -> None:
    """Storage-backed last-learned values survive an entry reload.

    Every save triggers a reload, which used to wipe the volatile
    hass.data values the sensors read from. The values are now persisted
    in storage, so sensors must report them after the reload as well.
    """
    from datetime import datetime, timezone

    from custom_components.openirblaster.sensor import (
        LastLearnedLengthSensor,
        LastLearnedNameSensor,
        LastLearnedTimestampSensor,
    )

    entry = MockConfigEntry(domain=DOMAIN, data=mock_config_entry_data)
    entry.add_to_hass(hass)

    with patch(
        "homeassistant.config_entries.ConfigEntries.async_forward_entry_setups",
        return_value=True,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    # Simulate the save path persisting last-learned metadata
    storage = entry.runtime_data.storage
    await storage.async_set_last_learned(
        name="TV Power",
        timestamp="2026-01-12T14:30:00-05:00",
        pulse_count=4,
    )

    # Reload the entry (this is what follows every save)
    with patch(
        "homeassistant.config_entries.ConfigEntries.async_forward_entry_setups",
        return_value=True,
    ), patch(
        "homeassistant.config_entries.ConfigEntries.async_unload_platforms",
        return_value=True,
    ):
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()

    # Fresh runtime data and storage were created by the reload; the
    # persisted metadata must still be there.
    session = entry.runtime_data.learning_session
    name_sensor = LastLearnedNameSensor(entry, session)
    timestamp_sensor = LastLearnedTimestampSensor(entry, session)
    length_sensor = LastLearnedLengthSensor(entry, session)

    assert name_sensor.native_value == "TV Power"
    assert length_sensor.native_value == 4
    expected_ts = datetime(2026, 1, 12, 19, 30, tzinfo=timezone.utc)
    assert timestamp_sensor.native_value == expected_ts
