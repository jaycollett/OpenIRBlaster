"""Button platform for OpenIRBlaster."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    ATTR_CARRIER_HZ,
    ATTR_CODE_ID,
    ATTR_CODE_NAME,
    ATTR_PULSES,
    CONF_DEVICE_ID,
    CONF_ESPHOME_DEVICE_NAME,
    DOMAIN,
    STATE_ARMED,
    STATE_IDLE,
    STATE_RECEIVED,
    UNIQUE_ID_CODE_BUTTON,
    UNIQUE_ID_LEARN_BUTTON,
    UNIQUE_ID_SEND_LAST_BUTTON,
)
from .learning import LearningSession
from .storage import OpenIRBlasterStorage

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up OpenIRBlaster button entities."""
    storage: OpenIRBlasterStorage = hass.data[DOMAIN][entry.entry_id]["storage"]
    learning_session: LearningSession = hass.data[DOMAIN][entry.entry_id][
        "learning_session"
    ]

    entities: list[ButtonEntity] = []

    # Learn button
    entities.append(LearnButton(entry, learning_session))

    # Send last learned button
    entities.append(SendLastButton(entry, learning_session))

    # Button for each stored code
    for code in storage.get_codes():
        entities.append(
            CodeButton(
                entry,
                code[ATTR_CODE_ID],
                code[ATTR_CODE_NAME],
                code[ATTR_CARRIER_HZ],
                code[ATTR_PULSES],
            )
        )

    async_add_entities(entities)


class OpenIRBlasterButtonBase(ButtonEntity):
    """Base class for OpenIRBlaster buttons."""

    _attr_has_entity_name = True

    def __init__(self, entry: ConfigEntry) -> None:
        """Initialize the button."""
        self._entry = entry
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.data[CONF_DEVICE_ID])},
        )


class LearnButton(OpenIRBlasterButtonBase):
    """Button to start learning a new IR code."""

    def __init__(self, entry: ConfigEntry, learning_session: LearningSession) -> None:
        """Initialize the learn button."""
        super().__init__(entry)
        self._learning_session = learning_session
        self._attr_unique_id = UNIQUE_ID_LEARN_BUTTON.format(entry_id=entry.entry_id)
        self._attr_name = "Learn IR Code"
        self._attr_icon = "mdi:remote-tv"

    async def async_press(self) -> None:
        """Handle the button press."""
        if self._learning_session.state != STATE_IDLE:
            _LOGGER.warning(
                "Cannot start learning: session in state %s",
                self._learning_session.state,
            )
            return

        success = await self._learning_session.async_start_learning()
        if success:
            _LOGGER.info("Learning session started")
        else:
            _LOGGER.error("Failed to start learning session")


class SendLastButton(OpenIRBlasterButtonBase):
    """Button to send the last learned code (for debugging)."""

    def __init__(self, entry: ConfigEntry, learning_session: LearningSession) -> None:
        """Initialize the send last button."""
        super().__init__(entry)
        self._learning_session = learning_session
        self._attr_unique_id = UNIQUE_ID_SEND_LAST_BUTTON.format(
            entry_id=entry.entry_id
        )
        self._attr_name = "Send Last Learned"
        self._attr_icon = "mdi:send"

    async def async_press(self) -> None:
        """Handle the button press."""
        pending_code = self._learning_session.pending_code
        if pending_code is None:
            _LOGGER.warning("No pending code to send")
            return

        # Call ESPHome send_ir_raw service
        # Normalize device name: ESPHome uses underscores in service names
        device_name = self._entry.data[CONF_ESPHOME_DEVICE_NAME].replace("-", "_")
        service_name = f"{device_name}_send_ir_raw"
        try:
            await self.hass.services.async_call(
                "esphome",
                service_name,
                {
                    "carrier_hz": pending_code.carrier_hz,
                    "code": pending_code.pulses,
                },
                blocking=True,
            )
            _LOGGER.info("Sent last learned code")
        except Exception as err:
            _LOGGER.error("Failed to send last learned code: %s", err)


class CodeButton(OpenIRBlasterButtonBase):
    """Button to send a specific stored IR code."""

    def __init__(
        self,
        entry: ConfigEntry,
        code_id: str,
        name: str,
        carrier_hz: int,
        pulses: list[int],
    ) -> None:
        """Initialize the code button."""
        super().__init__(entry)
        self._code_id = code_id
        self._carrier_hz = carrier_hz
        self._pulses = pulses
        self._attr_unique_id = UNIQUE_ID_CODE_BUTTON.format(
            entry_id=entry.entry_id, code_id=code_id
        )
        self._attr_name = name
        self._attr_icon = "mdi:remote"

    async def async_press(self) -> None:
        """Handle the button press."""
        # Normalize device name: ESPHome uses underscores in service names
        device_name = self._entry.data[CONF_ESPHOME_DEVICE_NAME].replace("-", "_")
        service_name = f"{device_name}_send_ir_raw"
        try:
            await self.hass.services.async_call(
                "esphome",
                service_name,
                {
                    "carrier_hz": self._carrier_hz,
                    "code": self._pulses,
                },
                blocking=True,
            )
            _LOGGER.info("Sent code %s", self._code_id)
        except Exception as err:
            _LOGGER.error("Failed to send code %s: %s", self._code_id, err)
            # TODO: Create persistent notification for user
