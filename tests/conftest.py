"""Fixtures for OpenIRBlaster integration tests."""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import AsyncMock, patch

import pytest

from homeassistant.core import HomeAssistant

from custom_components.openirblaster.const import (
    CONF_DEVICE_ID,
    CONF_ESPHOME_DEVICE_NAME,
    CONF_LEARNING_SWITCH_ENTITY_ID,
    DOMAIN,
)

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom integrations."""
    yield


@pytest.fixture
def mock_config_entry_data():
    """Return mock config entry data."""
    return {
        CONF_ESPHOME_DEVICE_NAME: "openirblaster_test",
        CONF_DEVICE_ID: "openirblaster-test123",
        CONF_LEARNING_SWITCH_ENTITY_ID: "switch.openirblaster_test_ir_learning_mode",
    }


@pytest.fixture
def mock_learned_code_data():
    """Return mock learned code event data."""
    return {
        "device_id": "openirblaster-test123",
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
