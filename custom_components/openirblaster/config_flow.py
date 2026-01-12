"""Config flow for OpenIRBlaster integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import entity_registry as er

from .const import (
    CONF_DEVICE_ID,
    CONF_ESPHOME_DEVICE_NAME,
    CONF_LEARNING_SWITCH_ENTITY_ID,
    DEFAULT_LEARNING_SWITCH_PATTERN,
    DOMAIN,
    STATE_RECEIVED,
)
from .learning import LearnedCode

_LOGGER = logging.getLogger(__name__)


class OpenIRBlasterConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for OpenIRBlaster."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors = {}

        if user_input is not None:
            device_name = user_input[CONF_ESPHOME_DEVICE_NAME]
            device_id = user_input.get(CONF_DEVICE_ID, device_name)

            # Generate learning switch entity ID if not provided
            # Normalize device name: replace hyphens with underscores for entity IDs
            normalized_device_name = device_name.replace("-", "_")
            learning_switch_entity_id = user_input.get(
                CONF_LEARNING_SWITCH_ENTITY_ID,
                DEFAULT_LEARNING_SWITCH_PATTERN.format(device=normalized_device_name),
            )

            # Validate that the learning switch exists
            entity_registry = er.async_get(self.hass)
            if not entity_registry.async_get(learning_switch_entity_id):
                # Check if it exists in state registry
                state = self.hass.states.get(learning_switch_entity_id)
                if state is None:
                    errors["base"] = "entity_not_found"
                    _LOGGER.warning(
                        "Learning switch entity not found: %s", learning_switch_entity_id
                    )

            if not errors:
                # Create unique ID from device_id
                await self.async_set_unique_id(device_id)
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=f"OpenIRBlaster {device_name}",
                    data={
                        CONF_ESPHOME_DEVICE_NAME: device_name,
                        CONF_DEVICE_ID: device_id,
                        CONF_LEARNING_SWITCH_ENTITY_ID: learning_switch_entity_id,
                    },
                )

        # Show form
        data_schema = vol.Schema(
            {
                vol.Required(CONF_ESPHOME_DEVICE_NAME): str,
                vol.Optional(CONF_DEVICE_ID): str,
                vol.Optional(CONF_LEARNING_SWITCH_ENTITY_ID): str,
            }
        )

        return self.async_show_form(
            step_id="user", data_schema=data_schema, errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> OpenIRBlasterOptionsFlow:
        """Get the options flow for this handler."""
        return OpenIRBlasterOptionsFlow(config_entry)


class OpenIRBlasterOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow for OpenIRBlaster."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        # Check if there's a pending learned code
        entry_id = self.config_entry.entry_id
        if DOMAIN not in self.hass.data or entry_id not in self.hass.data[DOMAIN]:
            return self.async_abort(reason="not_loaded")

        learning_session = self.hass.data[DOMAIN][entry_id]["learning_session"]

        if learning_session.state == STATE_RECEIVED and learning_session.pending_code:
            return await self.async_step_save_code(user_input)

        # Show options menu
        return self.async_show_menu(
            step_id="init",
            menu_options=["manage_codes", "settings"],
        )

    async def async_step_save_code(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Save a pending learned code."""
        entry_id = self.config_entry.entry_id
        storage = self.hass.data[DOMAIN][entry_id]["storage"]
        learning_session = self.hass.data[DOMAIN][entry_id]["learning_session"]

        pending_code: LearnedCode = learning_session.pending_code

        if user_input is not None:
            name = user_input[CONF_NAME]
            tags = user_input.get("tags", "").split(",")
            tags = [tag.strip() for tag in tags if tag.strip()]
            notes = user_input.get("notes", "")

            # Save code to storage
            await storage.async_add_code(
                name=name,
                carrier_hz=pending_code.carrier_hz,
                pulses=pending_code.pulses,
                tags=tags,
                notes=notes,
            )

            # Clear pending code
            learning_session.clear_pending()

            # Reload entry to create new button entity
            self.hass.async_create_task(
                self.hass.config_entries.async_reload(entry_id)
            )

            return self.async_create_entry(title="", data={})

        # Show form to name the code
        data_schema = vol.Schema(
            {
                vol.Required(CONF_NAME): str,
                vol.Optional("tags"): str,
                vol.Optional("notes"): str,
            }
        )

        return self.async_show_form(
            step_id="save_code",
            data_schema=data_schema,
            description_placeholders={
                "carrier_hz": str(pending_code.carrier_hz),
                "pulse_count": str(len(pending_code.pulses)),
                "timestamp": pending_code.timestamp,
            },
        )

    async def async_step_manage_codes(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage stored codes."""
        # Placeholder for future code management UI
        return self.async_abort(reason="not_implemented")

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage integration settings."""
        # Placeholder for future settings UI
        return self.async_abort(reason="not_implemented")
