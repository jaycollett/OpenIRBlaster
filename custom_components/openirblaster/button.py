"""Button platform for OpenIRBlaster."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
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
    STATE_CANCELLED,
    STATE_IDLE,
    STATE_RECEIVED,
    STATE_TIMEOUT,
    UNIQUE_ID_CODE_BUTTON,
    UNIQUE_ID_CODE_NAME_INPUT,
    UNIQUE_ID_LEARN_BUTTON,
    UNIQUE_ID_SEND_LAST_BUTTON,
)
from .learning import LearnedCode, LearningSession
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

    # Button for each stored code (send button + delete button)
    for code in storage.get_codes():
        # Send button
        entities.append(
            CodeButton(
                entry,
                code[ATTR_CODE_ID],
                code[ATTR_CODE_NAME],
                code[ATTR_CARRIER_HZ],
                code[ATTR_PULSES],
            )
        )
        # Delete button
        entities.append(
            DeleteCodeButton(
                entry,
                code[ATTR_CODE_ID],
                code[ATTR_CODE_NAME],
            )
        )

    async_add_entities(entities)


class OpenIRBlasterButtonBase(ButtonEntity):
    """Base class for OpenIRBlaster buttons."""

    _attr_has_entity_name = True

    def __init__(self, entry: ConfigEntry, use_controls_device: bool = False) -> None:
        """Initialize the button.

        Args:
            entry: Config entry
            use_controls_device: If True, assigns to controls device; if False, to main device
        """
        self._entry = entry
        device_id = entry.data[CONF_DEVICE_ID]
        # Reference either main device or controls device
        device_identifier = f"{device_id}_controls" if use_controls_device else device_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_identifier)},
        )


class LearnButton(OpenIRBlasterButtonBase):
    """Button to start learning a new IR code."""

    def __init__(
        self,
        entry: ConfigEntry,
        learning_session: LearningSession,
    ) -> None:
        """Initialize the learn button."""
        super().__init__(entry, use_controls_device=True)  # Assign to controls device
        self._learning_session = learning_session
        self._attr_unique_id = UNIQUE_ID_LEARN_BUTTON.format(entry_id=entry.entry_id)
        self._attr_name = "Learn IR Code"
        self._attr_icon = "mdi:remote-tv"

        # Store entry for later entity ID lookup
        self._text_entity_unique_id = UNIQUE_ID_CODE_NAME_INPUT.format(entry_id=entry.entry_id)
        self._pending_save_name: str | None = None

    async def async_press(self) -> None:
        """Handle the button press."""
        # Reset any previous session (except if currently armed/listening)
        if self._learning_session.state != STATE_IDLE:
            if self._learning_session.state == STATE_ARMED:
                _LOGGER.info("Learning session already active, ignoring button press")
                return
            else:
                _LOGGER.info("Resetting learning session from state %s to idle", self._learning_session.state)
                await self._learning_session.async_clear_pending()

        # Find text entity using entity registry
        registry = er.async_get(self.hass)
        text_entity_entry = registry.async_get_entity_id(
            "text",
            DOMAIN,
            self._text_entity_unique_id
        )

        if not text_entity_entry:
            _LOGGER.error("Cannot find Code Name text entity in registry")
            return

        text_entity_id = text_entity_entry

        # Read the text entity value
        text_state = self.hass.states.get(text_entity_id)
        if (not text_state or not text_state.state or
            text_state.state.strip() == "" or
            text_state.state == "unavailable" or
            text_state.state.strip() == "Enter Code Name"):
            # Show error notification
            await self.hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "notification_id": f"openirblaster_no_name_{self._entry.entry_id}",
                    "title": "OpenIRBlaster - Name Required",
                    "message": (
                        "Please enter a name for the IR code in the **Code Name** "
                        "field before pressing the Learn button."
                    ),
                },
            )
            _LOGGER.warning("Cannot start learning: no code name provided")
            return

        # Store the code name for the callback
        self._pending_save_name = text_state.state.strip()

        # Register callback to handle learning completion
        self._learning_session.register_callback(self._handle_learning_complete)

        # Start learning
        success = await self._learning_session.async_start_learning()
        if success:
            _LOGGER.info("Learning session started for code: %s", self._pending_save_name)
        else:
            _LOGGER.error("Failed to start learning session")
            # Unregister callback if start failed
            self._learning_session.unregister_callback(self._handle_learning_complete)
            self._pending_save_name = None

    def _handle_learning_complete(self, state: str, code: LearnedCode | None) -> None:
        """Handle learning session state changes."""
        if state == STATE_RECEIVED and code and self._pending_save_name:
            # Schedule the save operation
            asyncio.create_task(self._async_save_learned_code())

    async def _async_save_learned_code(self) -> None:
        """Save the learned code with the pending name."""
        if not self._pending_save_name:
            return

        try:
            # Get storage from hass.data
            storage: OpenIRBlasterStorage = self.hass.data[DOMAIN][self._entry.entry_id]["storage"]

            # Check for duplicate name
            if storage.name_exists(self._pending_save_name):
                _LOGGER.warning("Code name '%s' already exists", self._pending_save_name)
                # Show error notification
                await self.hass.services.async_call(
                    "persistent_notification",
                    "create",
                    {
                        "notification_id": f"openirblaster_duplicate_{self._entry.entry_id}",
                        "title": "OpenIRBlaster - Duplicate Name",
                        "message": (
                            f"A code named **{self._pending_save_name}** already exists. "
                            f"Please choose a different name."
                        ),
                    },
                )
                # Clear the pending code and reset learning session
                await self._learning_session.async_clear_pending()
                return

            # Get the pending code
            pending_code = self._learning_session.pending_code
            if not pending_code:
                _LOGGER.error("No pending code to save")
                return

            # Save the code
            await storage.async_add_code(
                name=self._pending_save_name,
                carrier_hz=pending_code.carrier_hz,
                pulses=pending_code.pulses,
            )

            _LOGGER.info("Saved learned code as: %s", self._pending_save_name)

            # Store all learned code data in hass.data so sensors can display it after reload
            self.hass.data[DOMAIN][self._entry.entry_id]["last_learned_name"] = self._pending_save_name
            self.hass.data[DOMAIN][self._entry.entry_id]["last_learned_timestamp"] = pending_code.timestamp
            self.hass.data[DOMAIN][self._entry.entry_id]["last_learned_pulse_count"] = len(pending_code.pulses)

            # Clear the text entity - find it using entity registry
            registry = er.async_get(self.hass)
            text_entity_id = registry.async_get_entity_id(
                "text",
                DOMAIN,
                self._text_entity_unique_id
            )
            if text_entity_id:
                await self.hass.services.async_call(
                    "text",
                    "set_value",
                    {
                        "entity_id": text_entity_id,
                        "value": "Enter Code Name",
                    },
                )

            # Clear the pending code in learning session
            await self._learning_session.async_clear_pending()

            # Reload config entry to create new button entity
            await self.hass.config_entries.async_reload(self._entry.entry_id)

        except Exception as err:
            _LOGGER.error("Failed to save learned code: %s", err, exc_info=True)
        finally:
            # Cleanup: unregister callback and clear pending name
            self._learning_session.unregister_callback(self._handle_learning_complete)
            self._pending_save_name = None


class SendLastButton(OpenIRBlasterButtonBase):
    """Button to send the last learned code (for debugging)."""

    def __init__(
        self,
        entry: ConfigEntry,
        learning_session: LearningSession,
    ) -> None:
        """Initialize the send last button."""
        super().__init__(entry, use_controls_device=True)  # Assign to controls device
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


class DeleteCodeButton(OpenIRBlasterButtonBase):
    """Button to delete a specific stored IR code."""

    _attr_entity_registry_enabled_default = False  # Disabled by default for safety

    def __init__(
        self,
        entry: ConfigEntry,
        code_id: str,
        name: str,
    ) -> None:
        """Initialize the delete button."""
        super().__init__(entry, use_controls_device=True)  # Assign to controls device
        self._code_id = code_id
        self._attr_unique_id = f"{entry.entry_id}_{code_id}_delete"
        self._attr_name = f"Delete {name}"
        self._attr_icon = "mdi:delete"

    async def async_press(self) -> None:
        """Handle the button press - delete the code."""
        _LOGGER.info("Delete button pressed for code %s", self._code_id)

        # Get entity registry
        registry = er.async_get(self.hass)

        # Find both the send button and this delete button
        send_button_unique_id = UNIQUE_ID_CODE_BUTTON.format(
            entry_id=self._entry.entry_id, code_id=self._code_id
        )
        delete_button_unique_id = f"{self._entry.entry_id}_{self._code_id}_delete"

        send_button_entity_id = registry.async_get_entity_id(
            "button", DOMAIN, send_button_unique_id
        )
        delete_button_entity_id = registry.async_get_entity_id(
            "button", DOMAIN, delete_button_unique_id
        )

        try:
            # Get storage from hass.data
            storage: OpenIRBlasterStorage = self.hass.data[DOMAIN][self._entry.entry_id]["storage"]

            # Delete the code from storage
            success = await storage.async_delete_code(self._code_id)

            if success:
                _LOGGER.info("Successfully deleted code %s from storage", self._code_id)

                # Remove both button entities from entity registry
                if send_button_entity_id:
                    registry.async_remove(send_button_entity_id)
                    _LOGGER.info("Removed send button entity %s", send_button_entity_id)

                if delete_button_entity_id:
                    registry.async_remove(delete_button_entity_id)
                    _LOGGER.info("Removed delete button entity %s", delete_button_entity_id)

                # Show success notification
                await self.hass.services.async_call(
                    "persistent_notification",
                    "create",
                    {
                        "notification_id": f"openirblaster_deleted_{self._code_id}",
                        "title": "OpenIRBlaster - Code Deleted",
                        "message": f"IR code **{self._attr_name.replace('Delete ', '')}** has been deleted.",
                    },
                )
            else:
                _LOGGER.error("Failed to delete code %s - code not found in storage", self._code_id)
                # Show error notification
                await self.hass.services.async_call(
                    "persistent_notification",
                    "create",
                    {
                        "notification_id": f"openirblaster_delete_error_{self._code_id}",
                        "title": "OpenIRBlaster - Delete Failed",
                        "message": f"Failed to delete IR code **{self._attr_name.replace('Delete ', '')}**. Code not found in storage.",
                    },
                )
        except Exception as err:
            _LOGGER.error("Error deleting code %s: %s", self._code_id, err, exc_info=True)
            # Show error notification
            await self.hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "notification_id": f"openirblaster_delete_error_{self._code_id}",
                    "title": "OpenIRBlaster - Delete Failed",
                    "message": f"Error deleting IR code: {err}",
                },
            )
