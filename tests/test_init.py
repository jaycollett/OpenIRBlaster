"""Tests for __init__ module."""

from __future__ import annotations

from unittest.mock import patch

from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from custom_components.openirblaster import async_setup_entry, async_unload_entry
from custom_components.openirblaster.const import CONF_MAC_ADDRESS, DOMAIN


async def test_setup_entry(
    hass: HomeAssistant, mock_config_entry_data: dict
) -> None:
    """Test setting up a config entry."""
    entry = MockConfigEntry(domain=DOMAIN, data=mock_config_entry_data)
    entry.add_to_hass(hass)

    with patch(
        "homeassistant.config_entries.ConfigEntries.async_forward_entry_setups",
        return_value=True,
    ) as mock_forward:
        assert await async_setup_entry(hass, entry)
        mock_forward.assert_called_once()
        # Verify platforms
        call_args = mock_forward.call_args[0]
        assert call_args[0] == entry
        assert Platform.BUTTON in call_args[1]
        assert Platform.SENSOR in call_args[1]

    # Verify data structure
    assert DOMAIN in hass.data
    assert entry.entry_id in hass.data[DOMAIN]
    assert "storage" in hass.data[DOMAIN][entry.entry_id]
    assert "learning_session" in hass.data[DOMAIN][entry.entry_id]


async def test_unload_entry(
    hass: HomeAssistant, mock_config_entry_data: dict
) -> None:
    """Test unloading a config entry."""
    entry = MockConfigEntry(domain=DOMAIN, data=mock_config_entry_data)
    entry.add_to_hass(hass)

    with patch(
        "homeassistant.config_entries.ConfigEntries.async_forward_entry_setups",
        return_value=True,
    ):
        await async_setup_entry(hass, entry)

    with patch(
        "homeassistant.config_entries.ConfigEntries.async_unload_platforms",
        return_value=True,
    ) as mock_unload:
        assert await async_unload_entry(hass, entry)
        mock_unload.assert_called_once()

    # Verify cleanup
    assert entry.entry_id not in hass.data[DOMAIN]


async def test_setup_entry_backfills_mac_from_esphome_device(
    hass: HomeAssistant, mock_config_entry_data: dict
) -> None:
    """When MAC is missing, setup back-fills it from the ESPHome device registry.

    Older config entries predate MAC capture in the config flow. On setup
    we look up the ESPHome device by node name in the device registry and
    back-fill the MAC so text_sensor Strategy 1 (MAC-based resolver) works
    without requiring the user to remove and re-add the integration.
    """
    assert CONF_MAC_ADDRESS not in mock_config_entry_data

    # Register a fake ESPHome config entry and a device under it with a MAC
    esphome_entry = MockConfigEntry(domain="esphome", data={})
    esphome_entry.add_to_hass(hass)
    dev_reg = dr.async_get(hass)
    dev_reg.async_get_or_create(
        config_entry_id=esphome_entry.entry_id,
        connections={(dr.CONNECTION_NETWORK_MAC, "aa:bb:cc:dd:ee:ff")},
        identifiers={("esphome", "aabbccddeeff")},
        name=mock_config_entry_data["device_id"],
    )

    entry = MockConfigEntry(domain=DOMAIN, data=mock_config_entry_data)
    entry.add_to_hass(hass)

    with patch(
        "homeassistant.config_entries.ConfigEntries.async_forward_entry_setups",
        return_value=True,
    ):
        assert await async_setup_entry(hass, entry)

    # Entry data was updated in place with the back-filled MAC
    assert entry.data.get(CONF_MAC_ADDRESS) == "aa:bb:cc:dd:ee:ff"
    # Learning session picked up the back-filled MAC
    session = hass.data[DOMAIN][entry.entry_id]["learning_session"]
    assert session.mac_address == "aa:bb:cc:dd:ee:ff"


async def test_setup_entry_mac_backfill_skipped_when_no_esphome_match(
    hass: HomeAssistant, mock_config_entry_data: dict
) -> None:
    """Setup proceeds without error when no matching ESPHome device exists.

    Back-fill is best-effort: if nothing matches, we log a warning and fall
    back to slug-based resolution (current behaviour pre-patch).
    """
    assert CONF_MAC_ADDRESS not in mock_config_entry_data

    entry = MockConfigEntry(domain=DOMAIN, data=mock_config_entry_data)
    entry.add_to_hass(hass)

    with patch(
        "homeassistant.config_entries.ConfigEntries.async_forward_entry_setups",
        return_value=True,
    ):
        assert await async_setup_entry(hass, entry)

    # No MAC was added (nothing to find)
    assert CONF_MAC_ADDRESS not in entry.data
    session = hass.data[DOMAIN][entry.entry_id]["learning_session"]
    assert session.mac_address is None
