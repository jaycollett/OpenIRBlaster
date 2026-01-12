"""Tests for storage module."""

from __future__ import annotations

import pytest

from homeassistant.core import HomeAssistant

from custom_components.openirblaster.const import (
    ATTR_CARRIER_HZ,
    ATTR_CODE_ID,
    ATTR_CODE_NAME,
    ATTR_PULSES,
    STORAGE_VERSION,
)
from custom_components.openirblaster.storage import OpenIRBlasterStorage


async def test_storage_initialization(hass: HomeAssistant) -> None:
    """Test storage initialization."""
    storage = OpenIRBlasterStorage(hass, "test_entry")
    data = await storage.async_load()

    assert data["version"] == STORAGE_VERSION
    assert data["device"]["config_entry_id"] == "test_entry"
    assert data["codes"] == []


async def test_add_code(hass: HomeAssistant) -> None:
    """Test adding a code to storage."""
    storage = OpenIRBlasterStorage(hass, "test_entry")
    await storage.async_load()

    code = await storage.async_add_code(
        name="Test Code",
        carrier_hz=38000,
        pulses=[9000, -4500, 560, -560],
        tags=["test"],
        notes="Test note",
    )

    assert code[ATTR_CODE_NAME] == "Test Code"
    assert code[ATTR_CARRIER_HZ] == 38000
    assert len(code[ATTR_PULSES]) == 4
    assert code[ATTR_CODE_ID] == "test_code"


async def test_id_collision_resolution(hass: HomeAssistant) -> None:
    """Test ID collision resolution."""
    storage = OpenIRBlasterStorage(hass, "test_entry")
    await storage.async_load()

    # Add first code
    code1 = await storage.async_add_code(
        name="TV Power", carrier_hz=38000, pulses=[1, 2, 3]
    )
    assert code1[ATTR_CODE_ID] == "tv_power"

    # Add second code with same name
    code2 = await storage.async_add_code(
        name="TV Power", carrier_hz=38000, pulses=[4, 5, 6]
    )
    assert code2[ATTR_CODE_ID] == "tv_power_2"

    # Add third code with same name
    code3 = await storage.async_add_code(
        name="TV Power", carrier_hz=38000, pulses=[7, 8, 9]
    )
    assert code3[ATTR_CODE_ID] == "tv_power_3"


async def test_get_code(hass: HomeAssistant) -> None:
    """Test retrieving a code by ID."""
    storage = OpenIRBlasterStorage(hass, "test_entry")
    await storage.async_load()

    await storage.async_add_code(name="Test", carrier_hz=38000, pulses=[1, 2, 3])

    code = storage.get_code("test")
    assert code is not None
    assert code[ATTR_CODE_NAME] == "Test"

    # Non-existent code
    assert storage.get_code("nonexistent") is None


async def test_update_code(hass: HomeAssistant) -> None:
    """Test updating a code."""
    storage = OpenIRBlasterStorage(hass, "test_entry")
    await storage.async_load()

    await storage.async_add_code(name="Original", carrier_hz=38000, pulses=[1, 2, 3])

    updated = await storage.async_update_code("original", name="Updated Name")
    assert updated[ATTR_CODE_NAME] == "Updated Name"
    assert updated[ATTR_CARRIER_HZ] == 38000  # Unchanged


async def test_delete_code(hass: HomeAssistant) -> None:
    """Test deleting a code."""
    storage = OpenIRBlasterStorage(hass, "test_entry")
    await storage.async_load()

    await storage.async_add_code(name="Delete Me", carrier_hz=38000, pulses=[1, 2, 3])

    assert storage.code_exists("delete_me")
    success = await storage.async_delete_code("delete_me")
    assert success
    assert not storage.code_exists("delete_me")


async def test_slug_generation(hass: HomeAssistant) -> None:
    """Test slug generation from various names."""
    storage = OpenIRBlasterStorage(hass, "test_entry")
    await storage.async_load()

    # Test special characters
    code1 = await storage.async_add_code(
        name="TV #1 Power!", carrier_hz=38000, pulses=[1]
    )
    assert code1[ATTR_CODE_ID] == "tv_1_power"

    # Test spaces
    code2 = await storage.async_add_code(
        name="Living Room TV", carrier_hz=38000, pulses=[1]
    )
    assert code2[ATTR_CODE_ID] == "living_room_tv"

    # Test empty/special only
    code3 = await storage.async_add_code(name="###", carrier_hz=38000, pulses=[1])
    assert code3[ATTR_CODE_ID] == "code"
