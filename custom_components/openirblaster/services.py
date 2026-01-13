"""Services for OpenIRBlaster integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv

from .const import (
    ATTR_CARRIER_HZ,
    ATTR_CODE_ID,
    ATTR_PULSES,
    CONF_DEVICE_ID,
    CONF_ESPHOME_DEVICE_NAME,
    DOMAIN,
    SERVICE_DELETE_CODE,
    SERVICE_LEARN_START,
    SERVICE_RENAME_CODE,
    SERVICE_SAVE_PENDING,
    SERVICE_SEND_CODE,
)
from .learning import LearningSession
from .storage import OpenIRBlasterStorage

_LOGGER = logging.getLogger(__name__)

# Service schema definitions
LEARN_START_SCHEMA = vol.Schema(
    {
        vol.Required("config_entry_id"): cv.string,
        vol.Optional("timeout", default=30): cv.positive_int,
    }
)

SEND_CODE_SCHEMA = vol.Schema(
    {
        vol.Required("config_entry_id"): cv.string,
        vol.Required(ATTR_CODE_ID): cv.string,
        vol.Optional(ATTR_CARRIER_HZ): cv.positive_int,
        vol.Optional(ATTR_PULSES): vol.All(cv.ensure_list, [int]),
    }
)

DELETE_CODE_SCHEMA = vol.Schema(
    {
        vol.Required("config_entry_id"): cv.string,
        vol.Required(ATTR_CODE_ID): cv.string,
    }
)

RENAME_CODE_SCHEMA = vol.Schema(
    {
        vol.Required("config_entry_id"): cv.string,
        vol.Required(ATTR_CODE_ID): cv.string,
        vol.Required("new_name"): cv.string,
    }
)

SAVE_PENDING_SCHEMA = vol.Schema(
    {
        vol.Required("config_entry_id"): cv.string,
        vol.Required("name"): cv.string,
        vol.Optional("tags"): cv.string,  # Comma-separated tags
        vol.Optional("notes"): cv.string,
    }
)


async def async_setup_services(hass: HomeAssistant) -> None:
    """Set up services for OpenIRBlaster."""
    _LOGGER.info("Setting up OpenIRBlaster services")

    async def handle_learn_start(call: ServiceCall) -> None:
        """Handle learn_start service call."""
        entry_id = call.data["config_entry_id"]
        timeout = call.data.get("timeout", 30)

        if entry_id not in hass.data[DOMAIN]:
            _LOGGER.error("Config entry %s not found", entry_id)
            return

        learning_session: LearningSession = hass.data[DOMAIN][entry_id][
            "learning_session"
        ]
        learning_session.timeout = timeout
        success = await learning_session.async_start_learning()

        if success:
            _LOGGER.info("Learning session started for entry %s", entry_id)
        else:
            _LOGGER.error("Failed to start learning session for entry %s", entry_id)

    async def handle_send_code(call: ServiceCall) -> None:
        """Handle send_code service call."""
        entry_id = call.data["config_entry_id"]
        code_id = call.data[ATTR_CODE_ID]

        if entry_id not in hass.data[DOMAIN]:
            _LOGGER.error("Config entry %s not found", entry_id)
            return

        storage: OpenIRBlasterStorage = hass.data[DOMAIN][entry_id]["storage"]
        entry = hass.data[DOMAIN][entry_id]["config_entry"]

        # Get code from storage or use overrides
        code = storage.get_code(code_id)
        if code is None and (
            ATTR_CARRIER_HZ not in call.data or ATTR_PULSES not in call.data
        ):
            _LOGGER.error("Code %s not found and no override provided", code_id)
            return

        carrier_hz = call.data.get(ATTR_CARRIER_HZ, code.get(ATTR_CARRIER_HZ) if code else None)
        pulses = call.data.get(ATTR_PULSES, code.get(ATTR_PULSES) if code else None)

        # Call ESPHome service
        # Normalize device name: ESPHome uses underscores in service names
        device_name = entry.data[CONF_ESPHOME_DEVICE_NAME].replace("-", "_")
        service_name = f"{device_name}_send_ir_raw"
        try:
            await hass.services.async_call(
                "esphome",
                service_name,
                {
                    "carrier_hz": carrier_hz,
                    "code": pulses,
                },
                blocking=True,
            )
            _LOGGER.info("Sent code %s", code_id)
        except Exception as err:
            _LOGGER.error("Failed to send code %s: %s", code_id, err)

    async def handle_delete_code(call: ServiceCall) -> None:
        """Handle delete_code service call."""
        entry_id = call.data["config_entry_id"]
        code_id = call.data[ATTR_CODE_ID]

        if entry_id not in hass.data[DOMAIN]:
            _LOGGER.error("Config entry %s not found", entry_id)
            return

        storage: OpenIRBlasterStorage = hass.data[DOMAIN][entry_id]["storage"]
        success = await storage.async_delete_code(code_id)

        if success:
            _LOGGER.info("Deleted code %s", code_id)
            # Reload entry to remove button entity
            await hass.config_entries.async_reload(entry_id)
        else:
            _LOGGER.error("Failed to delete code %s", code_id)

    async def handle_rename_code(call: ServiceCall) -> None:
        """Handle rename_code service call."""
        entry_id = call.data["config_entry_id"]
        code_id = call.data[ATTR_CODE_ID]
        new_name = call.data["new_name"]

        if entry_id not in hass.data[DOMAIN]:
            _LOGGER.error("Config entry %s not found", entry_id)
            return

        storage: OpenIRBlasterStorage = hass.data[DOMAIN][entry_id]["storage"]
        code = await storage.async_update_code(code_id, name=new_name)

        if code:
            _LOGGER.info("Renamed code %s to %s", code_id, new_name)
            # Reload entry to update button entity name
            await hass.config_entries.async_reload(entry_id)
        else:
            _LOGGER.error("Failed to rename code %s", code_id)

    async def handle_save_pending(call: ServiceCall) -> None:
        """Handle save_pending service call - saves the pending learned code."""
        entry_id = call.data["config_entry_id"]
        name = call.data["name"]
        tags_str = call.data.get("tags", "")
        notes = call.data.get("notes", "")

        if entry_id not in hass.data[DOMAIN]:
            _LOGGER.error("Config entry %s not found", entry_id)
            return

        learning_session: LearningSession = hass.data[DOMAIN][entry_id]["learning_session"]
        storage: OpenIRBlasterStorage = hass.data[DOMAIN][entry_id]["storage"]

        # Check if there's a pending code
        if not learning_session.pending_code:
            _LOGGER.error("No pending code to save")
            return

        # Parse tags
        tags = [tag.strip() for tag in tags_str.split(",") if tag.strip()]

        # Save code to storage
        pending = learning_session.pending_code
        await storage.async_add_code(
            name=name,
            carrier_hz=pending.carrier_hz,
            pulses=pending.pulses,
            tags=tags,
            notes=notes,
        )

        _LOGGER.info("Saved pending code as: %s", name)

        # Clear pending code
        learning_session.clear_pending()

        # Reload entry to create new button entity
        await hass.config_entries.async_reload(entry_id)

    # Register services
    hass.services.async_register(
        DOMAIN, SERVICE_LEARN_START, handle_learn_start, schema=LEARN_START_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_SEND_CODE, handle_send_code, schema=SEND_CODE_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_DELETE_CODE, handle_delete_code, schema=DELETE_CODE_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_RENAME_CODE, handle_rename_code, schema=RENAME_CODE_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_SAVE_PENDING, handle_save_pending, schema=SAVE_PENDING_SCHEMA
    )


async def async_unload_services(hass: HomeAssistant) -> None:
    """Unload OpenIRBlaster services."""
    _LOGGER.info("Unloading OpenIRBlaster services")

    hass.services.async_remove(DOMAIN, SERVICE_LEARN_START)
    hass.services.async_remove(DOMAIN, SERVICE_SEND_CODE)
    hass.services.async_remove(DOMAIN, SERVICE_DELETE_CODE)
    hass.services.async_remove(DOMAIN, SERVICE_RENAME_CODE)
    hass.services.async_remove(DOMAIN, SERVICE_SAVE_PENDING)
