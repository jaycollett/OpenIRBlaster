"""Fixtures for OpenIRBlaster integration tests."""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from homeassistant.core import HomeAssistant

from custom_components.openirblaster.const import (
    CONF_DEVICE_ID,
    CONF_ESPHOME_DEVICE_NAME,
    CONF_LEARNING_SWITCH_ENTITY_ID,
    CONF_MAC_ADDRESS,
    DOMAIN,
)

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom integrations."""
    yield


@pytest.fixture(autouse=True)
async def setup_esphome_integration(hass: HomeAssistant):
    """Set up a mock ESPHome integration to satisfy dependencies.

    Patches the loader and setup to handle esphome as a mock integration.
    Also registers mock services that the integration may call.
    """
    from homeassistant import loader, setup
    from homeassistant.loader import Integration

    # Mark esphome as loaded
    hass.config.components.add("esphome")

    # Register mock persistent_notification services (used by learning.py)
    hass.services.async_register(
        "persistent_notification", "create", AsyncMock()
    )
    hass.services.async_register(
        "persistent_notification", "dismiss", AsyncMock()
    )

    # Store original function
    original_async_get_integration = loader.async_get_integration

    async def patched_async_get_integration(hass, domain):
        """Return a mock for esphome, otherwise call original."""
        if domain == "esphome":
            # Create a minimal mock Integration
            mock_integration = MagicMock(spec=Integration)
            mock_integration.domain = "esphome"
            mock_integration.name = "ESPHome"
            mock_integration.dependencies = []
            mock_integration.after_dependencies = []
            mock_integration.requirements = []
            mock_integration.config_flow = False
            mock_integration.platforms_are_loaded = MagicMock(return_value=True)
            mock_integration.async_get_platforms = AsyncMock(return_value={})
            mock_integration.async_get_component = AsyncMock(
                return_value=MagicMock(
                    async_setup=AsyncMock(return_value=True),
                    async_setup_entry=AsyncMock(return_value=True),
                    DOMAIN="esphome",
                )
            )
            return mock_integration
        return await original_async_get_integration(hass, domain)

    with patch.object(loader, "async_get_integration", patched_async_get_integration):
        yield


@pytest.fixture
def mock_config_entry_data():
    """Return mock config entry data."""
    from custom_components.openirblaster.const import CONF_ESPHOME_SERVICE_NAME

    return {
        CONF_ESPHOME_DEVICE_NAME: "openirblaster_test",
        CONF_DEVICE_ID: "openirblaster-test123",
        CONF_LEARNING_SWITCH_ENTITY_ID: "switch.openirblaster_test_ir_learning_mode",
        CONF_ESPHOME_SERVICE_NAME: "openirblaster_test_send_ir_raw",
    }


@pytest.fixture
def mock_config_entry_data_with_mac():
    """Return mock config entry data with MAC address."""
    from custom_components.openirblaster.const import CONF_ESPHOME_SERVICE_NAME

    return {
        CONF_ESPHOME_DEVICE_NAME: "openirblaster_test",
        CONF_DEVICE_ID: "openirblaster-test123",
        CONF_LEARNING_SWITCH_ENTITY_ID: "switch.openirblaster_test_ir_learning_mode",
        CONF_ESPHOME_SERVICE_NAME: "openirblaster_test_send_ir_raw",
        CONF_MAC_ADDRESS: "AA:BB:CC:DD:EE:FF",
    }


@pytest.fixture
def mock_learned_code_data():
    """Return mock learned code event data."""
    return {
        "device_id": "openirblaster-test123",
        "mac_address": "AA:BB:CC:DD:EE:FF",
        "carrier_hz": 38000,
        "pulses_json": "[9000,-4500,560,-560,560,-1680,560,-560]",
        "timestamp": "2026-01-12T14:30:00-05:00",
        "rssi": -45,
    }


@pytest.fixture
def mock_stored_code():
    """Return mock stored code."""
    return {
        "id": "tv_power",
        "name": "TV Power",
        "carrier_hz": 38000,
        "pulses": [9000, -4500, 560, -560, 560, -1680, 560, -560],
        "created_at": "2026-01-12T14:30:00-05:00",
        "updated_at": "2026-01-12T14:30:00-05:00",
        "tags": ["tv"],
        "notes": "Power button for Samsung TV",
    }
