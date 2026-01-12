"""Tests for services module."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.core import HomeAssistant

from custom_components.openirblaster.const import (
    ATTR_CARRIER_HZ,
    ATTR_CODE_ID,
    ATTR_PULSES,
    DOMAIN,
    SERVICE_DELETE_CODE,
    SERVICE_LEARN_START,
    SERVICE_RENAME_CODE,
    SERVICE_SEND_CODE,
)
from custom_components.openirblaster.services import async_setup_services


async def test_setup_services(hass: HomeAssistant) -> None:
    """Test that services are registered."""
    await async_setup_services(hass)

    # Verify services are registered
    assert hass.services.has_service(DOMAIN, SERVICE_LEARN_START)
    assert hass.services.has_service(DOMAIN, SERVICE_SEND_CODE)
    assert hass.services.has_service(DOMAIN, SERVICE_DELETE_CODE)
    assert hass.services.has_service(DOMAIN, SERVICE_RENAME_CODE)


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

    learning_session = hass.data[DOMAIN][entry.entry_id]["learning_session"]

    with patch.object(learning_session, "async_start_learning", return_value=True):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_LEARN_START,
            {"config_entry_id": entry.entry_id, "timeout": 10},
            blocking=True,
        )

        # Verify timeout was set
        assert learning_session.timeout == 10


async def test_send_code_service(
    hass: HomeAssistant, mock_config_entry_data: dict, mock_stored_code: dict
) -> None:
    """Test send_code service."""
    entry = MockConfigEntry(domain=DOMAIN, data=mock_config_entry_data)
    entry.add_to_hass(hass)

    with patch(
        "homeassistant.config_entries.ConfigEntries.async_forward_entry_setups",
        return_value=True,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    # Add a code to storage
    storage = hass.data[DOMAIN][entry.entry_id]["storage"]
    await storage.async_add_code(
        name="Test Code",
        carrier_hz=38000,
        pulses=[9000, -4500],
    )

    # Register ESPHome service
    esphome_calls = []

    async def mock_esphome_service(call):
        esphome_calls.append(call)

    hass.services.async_register(
        "esphome", "openirblaster_test_send_ir_raw", mock_esphome_service
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
    storage = hass.data[DOMAIN][entry.entry_id]["storage"]
    await storage.async_add_code(
        name="Test Code",
        carrier_hz=38000,
        pulses=[9000, -4500],
    )

    assert len(storage.get_codes()) == 1

    with patch("homeassistant.config_entries.ConfigEntries.async_reload"):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_DELETE_CODE,
            {
                "config_entry_id": entry.entry_id,
                ATTR_CODE_ID: "test_code",
            },
            blocking=True,
        )

    # Verify code was deleted
    assert len(storage.get_codes()) == 0


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
    storage = hass.data[DOMAIN][entry.entry_id]["storage"]
    await storage.async_add_code(
        name="Old Name",
        carrier_hz=38000,
        pulses=[9000, -4500],
    )

    with patch("homeassistant.config_entries.ConfigEntries.async_reload"):
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

    # Verify code was renamed
    code = storage.get_code("old_name")
    assert code is not None
    assert code["name"] == "New Name"
