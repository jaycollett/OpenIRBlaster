"""Tests for config flow."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.openirblaster.const import (
    CONF_DEVICE_ID,
    CONF_ESPHOME_DEVICE_NAME,
    CONF_LEARNING_SWITCH_ENTITY_ID,
    DOMAIN,
    STATE_RECEIVED,
)


async def test_user_flow_success(hass: HomeAssistant) -> None:
    """Test successful user flow."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"

    # Mock the entity registry to simulate entity exists
    with patch(
        "custom_components.openirblaster.config_flow.er.async_get"
    ) as mock_get_er:
        mock_er = mock_get_er.return_value
        mock_er.async_get.return_value = None  # Entity not in registry

        # Mock state to simulate entity exists in state machine
        hass.states.async_set("switch.openirblaster_test_ir_learning_mode", "off")

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={
                CONF_ESPHOME_DEVICE_NAME: "openirblaster_test",
                CONF_DEVICE_ID: "openirblaster-test123",
                CONF_LEARNING_SWITCH_ENTITY_ID: "switch.openirblaster_test_ir_learning_mode",
            },
        )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == "OpenIRBlaster openirblaster_test"
    assert result["data"][CONF_ESPHOME_DEVICE_NAME] == "openirblaster_test"
    assert result["data"][CONF_DEVICE_ID] == "openirblaster-test123"


async def test_user_flow_entity_not_found(hass: HomeAssistant) -> None:
    """Test user flow with entity not found."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    with patch(
        "custom_components.openirblaster.config_flow.er.async_get"
    ) as mock_get_er:
        mock_er = mock_get_er.return_value
        mock_er.async_get.return_value = None

        # Don't add state, so entity doesn't exist
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={
                CONF_ESPHOME_DEVICE_NAME: "openirblaster_test",
                CONF_LEARNING_SWITCH_ENTITY_ID: "switch.nonexistent",
            },
        )

    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "entity_not_found"}


async def test_user_flow_default_entity_id(hass: HomeAssistant) -> None:
    """Test user flow with default entity ID generation."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    with patch(
        "custom_components.openirblaster.config_flow.er.async_get"
    ) as mock_get_er:
        mock_er = mock_get_er.return_value
        mock_er.async_get.return_value = None

        # Set state for default entity ID
        hass.states.async_set("switch.mydevice_ir_learning_mode", "off")

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={
                CONF_ESPHOME_DEVICE_NAME: "mydevice",
            },
        )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert (
        result["data"][CONF_LEARNING_SWITCH_ENTITY_ID]
        == "switch.mydevice_ir_learning_mode"
    )


async def test_duplicate_entry(hass: HomeAssistant) -> None:
    """Test that duplicate entries are prevented."""
    # Create existing entry
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_ESPHOME_DEVICE_NAME: "openirblaster_test",
            CONF_DEVICE_ID: "openirblaster-test123",
            CONF_LEARNING_SWITCH_ENTITY_ID: "switch.openirblaster_test_ir_learning_mode",
        },
        unique_id="openirblaster-test123",
    )
    entry.add_to_hass(hass)

    # Try to create duplicate
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    with patch(
        "custom_components.openirblaster.config_flow.er.async_get"
    ) as mock_get_er:
        mock_er = mock_get_er.return_value
        mock_er.async_get.return_value = None
        hass.states.async_set("switch.openirblaster_test_ir_learning_mode", "off")

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={
                CONF_ESPHOME_DEVICE_NAME: "openirblaster_test",
                CONF_DEVICE_ID: "openirblaster-test123",
            },
        )

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_options_flow_no_pending_code(
    hass: HomeAssistant, mock_config_entry_data: dict
) -> None:
    """Test options flow when no code is pending."""
    entry = MockConfigEntry(domain=DOMAIN, data=mock_config_entry_data)
    entry.add_to_hass(hass)

    # Set up entry but don't start learning
    with patch(
        "homeassistant.config_entries.ConfigEntries.async_forward_entry_setups",
        return_value=True,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)

    assert result["type"] == FlowResultType.MENU
    assert "manage_codes" in result["menu_options"]
    assert "settings" in result["menu_options"]


async def test_options_flow_save_pending_code(
    hass: HomeAssistant, mock_config_entry_data: dict, mock_learned_code_data: dict
) -> None:
    """Test options flow to save a pending learned code."""
    entry = MockConfigEntry(domain=DOMAIN, data=mock_config_entry_data)
    entry.add_to_hass(hass)

    # Set up entry
    with patch(
        "homeassistant.config_entries.ConfigEntries.async_forward_entry_setups",
        return_value=True,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    # Simulate a pending learned code
    from custom_components.openirblaster.learning import LearnedCode

    learning_session = hass.data[DOMAIN][entry.entry_id]["learning_session"]
    learning_session._state = STATE_RECEIVED
    learning_session._pending_code = LearnedCode(
        carrier_hz=38000,
        pulses=[9000, -4500, 560, -560],
        timestamp="2026-01-12T14:30:00-05:00",
        device_id="openirblaster-test123",
    )

    # Start options flow
    result = await hass.config_entries.options.async_init(entry.entry_id)

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "save_code"

    # Save the code
    with patch(
        "homeassistant.config_entries.ConfigEntries.async_reload"
    ) as mock_reload:
        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            user_input={
                CONF_NAME: "TV Power",
                "tags": "tv, samsung",
                "notes": "Power button",
            },
        )

    assert result["type"] == FlowResultType.CREATE_ENTRY

    # Verify code was saved
    storage = hass.data[DOMAIN][entry.entry_id]["storage"]
    codes = storage.get_codes()
    assert len(codes) == 1
    assert codes[0]["name"] == "TV Power"
    assert codes[0]["carrier_hz"] == 38000
    assert "tv" in codes[0]["tags"]
