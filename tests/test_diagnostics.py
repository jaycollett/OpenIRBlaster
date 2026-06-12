"""Tests for the diagnostics module."""

from __future__ import annotations

from homeassistant.components.diagnostics import REDACTED
from homeassistant.core import HomeAssistant

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.openirblaster.const import (
    CONF_DEVICE_ID,
    CONF_ESPHOME_DEVICE_NAME,
    CONF_ESPHOME_SERVICE_NAME,
    CONF_LEARNING_SWITCH_ENTITY_ID,
    CONF_MAC_ADDRESS,
    DOMAIN,
)
from custom_components.openirblaster.diagnostics import (
    async_get_config_entry_diagnostics,
)


async def test_diagnostics_redacts_mac_and_device_identifiers(
    hass: HomeAssistant, mock_config_entry_data_with_mac
) -> None:
    """Config entry data must not leak the MAC address or device ids."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="OpenIRBlaster Test",
        data=mock_config_entry_data_with_mac,
    )
    entry.add_to_hass(hass)

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)

    entry_data = diagnostics["entry"]["data"]
    assert entry_data[CONF_MAC_ADDRESS] == REDACTED
    assert entry_data[CONF_DEVICE_ID] == REDACTED
    assert entry_data[CONF_ESPHOME_DEVICE_NAME] == REDACTED
    assert entry_data[CONF_ESPHOME_SERVICE_NAME] == REDACTED
    assert entry_data[CONF_LEARNING_SWITCH_ENTITY_ID] == REDACTED

    # Sanity: raw values must not appear anywhere in the diagnostics dump.
    dump = repr(diagnostics)
    assert mock_config_entry_data_with_mac[CONF_MAC_ADDRESS] not in dump
    assert mock_config_entry_data_with_mac[CONF_DEVICE_ID] not in dump
