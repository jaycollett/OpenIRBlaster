"""Text entities for OpenIRBlaster integration."""

from __future__ import annotations

import logging

from homeassistant.components.text import TextEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_DEVICE_ID, DOMAIN, UNIQUE_ID_CODE_NAME_INPUT

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up OpenIRBlaster text entities from a config entry."""
    device_id = entry.data[CONF_DEVICE_ID]

    entities = [
        OpenIRBlasterCodeNameText(entry, device_id),
    ]

    async_add_entities(entities)


class OpenIRBlasterCodeNameText(TextEntity):
    """Text entity for entering the name of the IR code to learn."""

    _attr_has_entity_name = True
    _attr_translation_key = "code_name_input"
    _attr_native_max = 100
    _attr_native_min = 0
    _attr_mode = "text"

    def __init__(self, entry: ConfigEntry, device_id: str) -> None:
        """Initialize the text entity."""
        self._entry = entry
        self._attr_unique_id = UNIQUE_ID_CODE_NAME_INPUT.format(entry_id=entry.entry_id)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
        )
        self._attr_native_value = "Enter Code Name"

    @property
    def native_value(self) -> str:
        """Return the current value."""
        return self._attr_native_value

    async def async_set_value(self, value: str) -> None:
        """Set the text value."""
        self._attr_native_value = value
        self.async_write_ha_state()
