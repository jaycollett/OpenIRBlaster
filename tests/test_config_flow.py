"""Tests for config flow."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr, entity_registry as er

from custom_components.openirblaster.const import (
    CONF_DEVICE_ID,
    CONF_ESPHOME_DEVICE_NAME,
    CONF_ESPHOME_SERVICE_NAME,
    CONF_LEARNING_SWITCH_ENTITY_ID,
    CONF_MAC_ADDRESS,
    DOMAIN,
    STATE_RECEIVED,
)


def _create_mock_esphome_config_entry(hass: HomeAssistant) -> MockConfigEntry:
    """Create a mock ESPHome config entry."""
    entry = MockConfigEntry(
        domain="esphome",
        data={"device_name": "openirblaster-test123"},
        entry_id="mock_esphome_entry",
    )
    entry.add_to_hass(hass)
    return entry


def _create_mock_device(
    hass: HomeAssistant,
    device_registry: dr.DeviceRegistry,
    device_id: str = "openirblaster-test123",
    mac_address: str | None = None,
) -> dr.DeviceEntry:
    """Create a mock OpenIRBlaster device in the registry."""
    # First ensure the mock ESPHome config entry exists
    if not hass.config_entries.async_get_entry("mock_esphome_entry"):
        _create_mock_esphome_config_entry(hass)

    return device_registry.async_get_or_create(
        config_entry_id="mock_esphome_entry",
        identifiers={("esphome", device_id)},
        manufacturer="jaycollett",
        model="openirblaster",
        name=f"OpenIRBlaster {device_id}",
    )


async def test_user_flow_no_devices(hass: HomeAssistant) -> None:
    """Test user flow when no devices are found."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    # Should abort because no OpenIRBlaster devices found
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "no_devices_found"


async def test_user_flow_success(hass: HomeAssistant) -> None:
    """Test successful user flow with device discovery."""
    device_registry = dr.async_get(hass)
    entity_registry = er.async_get(hass)

    # Create mock OpenIRBlaster device
    device = _create_mock_device(hass, device_registry)

    # Create the learning switch entity for this device
    entity_registry.async_get_or_create(
        "switch",
        "esphome",
        f"{device.id}-switch-ir_learning_mode",
        suggested_object_id="openirblaster_test123_ir_learning_mode",
        original_name="IR Learning Mode",
        device_id=device.id,
    )

    # Create MAC address sensor
    mac_entity = entity_registry.async_get_or_create(
        "sensor",
        "esphome",
        f"{device.id}-sensor-mac_address",
        suggested_object_id="openirblaster_test123_mac_address",
        original_name="MAC Address",
        device_id=device.id,
    )

    # Set states
    hass.states.async_set(
        "switch.openirblaster_test123_ir_learning_mode", "off"
    )
    hass.states.async_set(
        mac_entity.entity_id, "AA:BB:CC:DD:EE:FF"
    )

    # Register mock ESPHome service
    async def mock_esphome_service(call):
        pass

    hass.services.async_register(
        "esphome", "openirblaster_test123_send_ir_raw", mock_esphome_service
    )

    # Start flow
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"

    # Select the device
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={"device": "openirblaster-test123"},
    )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == "OpenIRBlaster openirblaster-test123"
    assert result["data"][CONF_ESPHOME_DEVICE_NAME] == "openirblaster-test123"
    assert result["data"][CONF_DEVICE_ID] == "openirblaster-test123"
    assert result["data"][CONF_MAC_ADDRESS] == "AA:BB:CC:DD:EE:FF"


async def test_user_flow_entity_not_found(hass: HomeAssistant) -> None:
    """Test user flow with learning switch entity not found."""
    device_registry = dr.async_get(hass)

    # Create mock device but NO learning switch entity
    _create_mock_device(hass, device_registry)

    # Register mock ESPHome service
    hass.services.async_register(
        "esphome", "openirblaster_test123_send_ir_raw", lambda call: None
    )

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    assert result["type"] == FlowResultType.FORM

    # Select the device - should fail due to missing learning switch
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={"device": "openirblaster-test123"},
    )

    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "entity_not_found"}


async def test_user_flow_service_not_found(hass: HomeAssistant) -> None:
    """Test user flow when ESPHome service not found."""
    device_registry = dr.async_get(hass)
    entity_registry = er.async_get(hass)

    # Create mock device and switch but NO ESPHome service
    device = _create_mock_device(hass, device_registry)

    entity_registry.async_get_or_create(
        "switch",
        "esphome",
        f"{device.id}-switch-ir_learning_mode",
        suggested_object_id="openirblaster_test123_ir_learning_mode",
        original_name="IR Learning Mode",
        device_id=device.id,
    )

    hass.states.async_set(
        "switch.openirblaster_test123_ir_learning_mode", "off"
    )

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={"device": "openirblaster-test123"},
    )

    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "service_not_found"}


async def test_duplicate_entry(hass: HomeAssistant) -> None:
    """Test that duplicate entries are prevented."""
    device_registry = dr.async_get(hass)
    entity_registry = er.async_get(hass)

    # Create existing config entry
    existing_entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_ESPHOME_DEVICE_NAME: "openirblaster-test123",
            CONF_DEVICE_ID: "openirblaster-test123",
            CONF_LEARNING_SWITCH_ENTITY_ID: "switch.openirblaster_test123_ir_learning_mode",
            CONF_ESPHOME_SERVICE_NAME: "openirblaster_test123_send_ir_raw",
            CONF_MAC_ADDRESS: "AA:BB:CC:DD:EE:FF",
        },
        unique_id="aabbccddeeff",  # MAC-based unique_id
    )
    existing_entry.add_to_hass(hass)

    # Create mock device
    device = _create_mock_device(hass, device_registry)

    entity_registry.async_get_or_create(
        "switch",
        "esphome",
        f"{device.id}-switch-ir_learning_mode",
        suggested_object_id="openirblaster_test123_ir_learning_mode",
        original_name="IR Learning Mode",
        device_id=device.id,
    )

    mac_entity = entity_registry.async_get_or_create(
        "sensor",
        "esphome",
        f"{device.id}-sensor-mac_address",
        suggested_object_id="openirblaster_test123_mac_address",
        original_name="MAC Address",
        device_id=device.id,
    )

    hass.states.async_set(
        "switch.openirblaster_test123_ir_learning_mode", "off"
    )
    hass.states.async_set(mac_entity.entity_id, "AA:BB:CC:DD:EE:FF")

    hass.services.async_register(
        "esphome", "openirblaster_test123_send_ir_raw", lambda call: None
    )

    # Try to add same device - should be filtered out as already configured
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    # Device should be filtered out, so no devices available
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "no_devices_found"


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
