"""Button platform for OpenIRBlaster."""

from __future__ import annotations

import asyncio
import logging

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
    CONF_MAC_ADDRESS,
    DOMAIN,
    STATE_ARMED,
    STATE_IDLE,
    STATE_RECEIVED,
    UNIQUE_ID_CODE_BUTTON,
    UNIQUE_ID_CODE_NAME_INPUT,
    UNIQUE_ID_LEARN_BUTTON,
    UNIQUE_ID_SEND_LAST_BUTTON,
)
from .helpers import get_esphome_service
from .learning import LearnedCode, LearningSession
from .storage import OpenIRBlasterStorage

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up OpenIRBlaster button entities."""
    _LOGGER.debug("Setting up button entities for entry %s", entry.entry_id)

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
    codes = storage.get_codes()
    _LOGGER.info(
        "Found %d stored IR codes for entry %s",
        len(codes),
        entry.entry_id,
    )

    for code in codes:
        _LOGGER.debug(
            "Creating button for code: %s (%s)",
            code.get(ATTR_CODE_ID),
            code.get(ATTR_CODE_NAME),
        )
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

    _LOGGER.info(
        "Adding %d button entities for entry %s",
        len(entities),
        entry.entry_id,
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
        mac_address = entry.data.get(CONF_MAC_ADDRESS)

        # Use MAC-based identifier if available (matches device registration in __init__.py)
        if mac_address:
            normalized_mac = mac_address.lower().replace(":", "")
            base_identifier = normalized_mac
        else:
            base_identifier = device_id

        # Reference either main device or controls device
        device_identifier = f"{base_identifier}_controls" if use_controls_device else base_identifier
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_identifier)},
        )


class LearnButton(OpenIRBlasterButtonBase):
    """Button to start learning a new IR code."""

    _attr_translation_key = "learn"

    def __init__(
        self,
        entry: ConfigEntry,
        learning_session: LearningSession,
    ) -> None:
        """Initialize the learn button."""
        super().__init__(entry, use_controls_device=True)  # Assign to controls device
        self._learning_session = learning_session
        self._attr_unique_id = UNIQUE_ID_LEARN_BUTTON.format(entry_id=entry.entry_id)
        self._attr_icon = "mdi:remote-tv"

        # Store entry for later entity ID lookup
        self._text_entity_unique_id = UNIQUE_ID_CODE_NAME_INPUT.format(entry_id=entry.entry_id)
        self._pending_save_name: str | None = None
        # Guard against two capture notifications scheduling two concurrent
        # save tasks (e.g. event and text_sensor paths racing, or a stray
        # STATE_RECEIVED callback arriving while a save is already in-flight).
        self._save_in_progress: bool = False

    async def async_added_to_hass(self) -> None:
        """Register the learning callback once, for the lifetime of the entity.

        Registering on every press leaks subscriptions: if a press times out
        or fails before reaching the save path, the old callback stays in the
        session's list. The next press adds another, and when STATE_RECEIVED
        eventually fires the save handler runs multiple times. Keeping a
        single lifetime registration and gating the handler on
        ``_pending_save_name`` / ``_save_in_progress`` avoids both problems.
        """
        await super().async_added_to_hass()
        self._learning_session.register_callback(self._handle_learning_complete)

    async def async_will_remove_from_hass(self) -> None:
        """Unregister the learning callback when the entity is removed."""
        self._learning_session.unregister_callback(self._handle_learning_complete)
        await super().async_will_remove_from_hass()

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
            text_state.state == "unavailable"):
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

        # Start learning (callback is registered for entity lifetime in
        # async_added_to_hass; nothing to register here)
        success = await self._learning_session.async_start_learning()
        if success:
            _LOGGER.info("Learning session started for code: %s", self._pending_save_name)
        else:
            _LOGGER.error("Failed to start learning session")
            self._pending_save_name = None

    def _handle_learning_complete(self, state: str, code: LearnedCode | None) -> None:
        """Handle learning session state changes.

        This is registered once for the entity lifetime. It is a no-op unless
        a press is currently in-flight (``_pending_save_name`` is set) and no
        save task is already running. This makes the callback safe against
        stray STATE_RECEIVED notifications and against multiple capture paths
        (event + text_sensor fallback) both firing for the same learn cycle.
        """
        _LOGGER.debug(
            "Learning callback: state=%s, code=%s, pending_name=%s, save_in_progress=%s",
            state,
            code is not None,
            self._pending_save_name,
            self._save_in_progress,
        )
        if state != STATE_RECEIVED or code is None or not self._pending_save_name:
            return
        if self._save_in_progress:
            _LOGGER.debug("Save already in progress, ignoring duplicate notification")
            return
        self._save_in_progress = True
        _LOGGER.info("Scheduling save of learned code: %s", self._pending_save_name)
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
                        "value": "",
                    },
                )

            # Clear the pending code in learning session
            await self._learning_session.async_clear_pending()

            # Reload config entry to create new button entity
            await self.hass.config_entries.async_reload(self._entry.entry_id)

        except Exception as err:
            _LOGGER.error("Failed to save learned code: %s", err, exc_info=True)
        finally:
            # Release save guard and clear pending name. The callback itself
            # is registered for the entity's lifetime (see
            # async_added_to_hass) so we do not unregister it here.
            self._pending_save_name = None
            self._save_in_progress = False


class SendLastButton(OpenIRBlasterButtonBase):
    """Button to send the last learned code (for debugging)."""

    _attr_translation_key = "send_last"

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
        self._attr_icon = "mdi:send"

    async def async_press(self) -> None:
        """Handle the button press."""
        pending_code = self._learning_session.pending_code
        if pending_code is None:
            _LOGGER.warning("No pending code to send")
            return

        # Call ESPHome send_ir_raw service (discovered at integration load time)
        service_name = get_esphome_service(self.hass, self._entry.entry_id)
        if not service_name:
            _LOGGER.error(
                "ESPHome service not found - cannot send IR code. "
                "Try reloading the integration if the device was renamed."
            )
            return

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
        # Call ESPHome send_ir_raw service (discovered at integration load time)
        service_name = get_esphome_service(self.hass, self._entry.entry_id)
        if not service_name:
            _LOGGER.error(
                "ESPHome service not found - cannot send IR code %s. "
                "Try reloading the integration if the device was renamed.",
                self._code_id,
            )
            return

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

