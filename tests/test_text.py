"""Tests for the code-name text platform."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.core import HomeAssistant

from custom_components.openirblaster.const import (
    CONF_DEVICE_ID,
    CONF_MAC_ADDRESS,
    DOMAIN,
)
from custom_components.openirblaster.text import OpenIRBlasterCodeNameText


def _make_entry(data: dict) -> MockConfigEntry:
    return MockConfigEntry(domain=DOMAIN, data=data)


async def test_initial_native_value_is_empty(
    mock_config_entry_data: dict,
) -> None:
    """A freshly created text entity starts blank (not a placeholder)."""
    entry = _make_entry(mock_config_entry_data)
    text_entity = OpenIRBlasterCodeNameText(entry)
    assert text_entity.native_value == ""


async def test_async_set_value_updates_state(
    hass: HomeAssistant, mock_config_entry_data: dict
) -> None:
    """Setting a value updates the reported native value."""
    entry = _make_entry(mock_config_entry_data)
    text_entity = OpenIRBlasterCodeNameText(entry)

    # async_write_ha_state requires a platform, which isn't set up in unit
    # tests that bypass EntityComponent. Patch it out so the test focuses on
    # native_value behaviour.
    with patch.object(
        OpenIRBlasterCodeNameText, "async_write_ha_state", autospec=True
    ) as mock_write:
        await text_entity.async_set_value("TV Power")
        assert text_entity.native_value == "TV Power"

        await text_entity.async_set_value("")
        assert text_entity.native_value == ""

        # Two writes -> two calls
        assert mock_write.call_count == 2


async def test_min_and_max_length(mock_config_entry_data: dict) -> None:
    """Min and max length constraints are respected."""
    entry = _make_entry(mock_config_entry_data)
    text_entity = OpenIRBlasterCodeNameText(entry)
    assert text_entity.native_min == 0
    assert text_entity.native_max == 100


async def test_assigned_to_controls_device_with_mac(
    mock_config_entry_data_with_mac: dict,
) -> None:
    """When MAC is available, the entity is attached to the MAC-based controls device."""
    entry = _make_entry(mock_config_entry_data_with_mac)
    text_entity = OpenIRBlasterCodeNameText(entry)

    normalized_mac = mock_config_entry_data_with_mac[CONF_MAC_ADDRESS].lower().replace(":", "")
    expected_identifier = (DOMAIN, f"{normalized_mac}_controls")
    assert expected_identifier in text_entity._attr_device_info["identifiers"]


async def test_assigned_to_controls_device_without_mac(
    mock_config_entry_data: dict,
) -> None:
    """When no MAC is set, fall back to device_id for the controls identifier."""
    entry = _make_entry(mock_config_entry_data)
    text_entity = OpenIRBlasterCodeNameText(entry)

    device_id = mock_config_entry_data[CONF_DEVICE_ID]
    expected_identifier = (DOMAIN, f"{device_id}_controls")
    assert expected_identifier in text_entity._attr_device_info["identifiers"]


async def test_unique_id_is_scoped_to_entry(mock_config_entry_data: dict) -> None:
    """Unique ID is namespaced by config entry so multiple installs coexist."""
    entry = _make_entry(mock_config_entry_data)
    text_entity = OpenIRBlasterCodeNameText(entry)
    assert text_entity.unique_id == f"{entry.entry_id}_code_name_input"
