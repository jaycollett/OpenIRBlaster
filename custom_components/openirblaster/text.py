"""Text entities for OpenIRBlaster integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.text import TextEntity, TextMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_DEVICE_ID,
    CONF_MAC_ADDRESS,
    DOMAIN,
    SIGNAL_CODE_ADDED,
    UNIQUE_ID_CODE_NAME_INPUT,
)

_LOGGER = logging.getLogger(__name__)

# Push-based integration: no parallel polling coordination needed
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up OpenIRBlaster text entities from a config entry."""
    entities = [
        OpenIRBlasterCodeNameText(entry),
    ]

    async_add_entities(entities)


class OpenIRBlasterCodeNameText(TextEntity):
    """Text entity for entering the name of the IR code to learn."""

    _attr_has_entity_name = True
    _attr_translation_key = "code_name_input"
    _attr_native_max = 100
    _attr_native_min = 0
    _attr_mode = TextMode.TEXT
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, entry: ConfigEntry) -> None:
        """Initialize the text entity."""
        self._entry = entry
        self._attr_unique_id = UNIQUE_ID_CODE_NAME_INPUT.format(entry_id=entry.entry_id)

        device_id = entry.data[CONF_DEVICE_ID]
        mac_address = entry.data.get(CONF_MAC_ADDRESS)

        # Use MAC-based identifier if available (matches device registration in __init__.py)
        if mac_address:
            normalized_mac = mac_address.lower().replace(":", "")
            base_identifier = normalized_mac
        else:
            base_identifier = device_id

        # Single main device; management entities are grouped via
        # entity_category instead of a separate virtual device.
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, base_identifier)},
        )
        self._attr_native_value = ""

    async def async_added_to_hass(self) -> None:
        """Subscribe to save notifications."""
        await super().async_added_to_hass()
        # Clear the input on ANY save path (Learn button, save_pending
        # service, options flow); they all dispatch SIGNAL_CODE_ADDED.
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_CODE_ADDED.format(entry_id=self._entry.entry_id),
                self._async_handle_code_saved,
            )
        )

    @callback
    def _async_handle_code_saved(self, code: dict[str, Any]) -> None:
        """Clear the input after a code was saved."""
        self._attr_native_value = ""
        self.async_write_ha_state()

    @property
    def native_value(self) -> str:
        """Return the current value."""
        return self._attr_native_value

    async def async_set_value(self, value: str) -> None:
        """Set the text value."""
        self._attr_native_value = value
        self.async_write_ha_state()
