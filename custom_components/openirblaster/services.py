"""Services for OpenIRBlaster integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .const import (
    ATTR_CARRIER_HZ,
    ATTR_CODE_ID,
    ATTR_PULSES,
    CONF_DEVICE_ID,
    DOMAIN,
    SERVICE_DELETE_CODE,
    SERVICE_LEARN_START,
    SERVICE_RENAME_CODE,
    SERVICE_SAVE_PENDING,
    SERVICE_SEND_CODE,
)
from .helpers import get_esphome_service
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
        vol.Optional("config_entry_id"): cv.string,
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
            raise ServiceValidationError(
                f"Config entry {entry_id} not found",
                translation_domain=DOMAIN,
                translation_key="config_entry_not_found",
            )

        learning_session: LearningSession = hass.data[DOMAIN][entry_id][
            "learning_session"
        ]
        learning_session.timeout = timeout
        success = await learning_session.async_start_learning()

        if success:
            _LOGGER.info("Learning session started for entry %s", entry_id)
        else:
            raise HomeAssistantError(
                f"Failed to start learning session for entry {entry_id}"
            )

    async def handle_send_code(call: ServiceCall) -> None:
        """Handle send_code service call."""
        entry_id = call.data["config_entry_id"]
        code_id = call.data[ATTR_CODE_ID]

        if entry_id not in hass.data[DOMAIN]:
            raise ServiceValidationError(
                f"Config entry {entry_id} not found",
                translation_domain=DOMAIN,
                translation_key="config_entry_not_found",
            )

        storage: OpenIRBlasterStorage = hass.data[DOMAIN][entry_id]["storage"]

        # Get code from storage or use overrides
        code = storage.get_code(code_id)
        if code is None and (
            ATTR_CARRIER_HZ not in call.data or ATTR_PULSES not in call.data
        ):
            raise ServiceValidationError(
                f"Code {code_id} not found and no override provided",
                translation_domain=DOMAIN,
                translation_key="code_not_found",
            )

        carrier_hz = call.data.get(ATTR_CARRIER_HZ, code.get(ATTR_CARRIER_HZ) if code else None)
        pulses = call.data.get(ATTR_PULSES, code.get(ATTR_PULSES) if code else None)

        # Call ESPHome service (discovered at integration load time)
        service_name = get_esphome_service(hass, entry_id)
        if not service_name:
            raise HomeAssistantError(
                f"ESPHome service not found - cannot send IR code {code_id}. "
                "Try reloading the integration if the device was renamed."
            )

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
            raise HomeAssistantError(f"Failed to send code {code_id}: {err}") from err

    async def handle_delete_code(call: ServiceCall) -> None:
        """Handle delete_code service call."""
        code_id = call.data[ATTR_CODE_ID]
        entry_id = call.data.get("config_entry_id")

        # If no config_entry_id provided, find it by searching for the code
        if not entry_id:
            _LOGGER.debug("No config_entry_id provided, searching for code %s", code_id)
            for check_entry_id in hass.data.get(DOMAIN, {}):
                storage: OpenIRBlasterStorage = hass.data[DOMAIN][check_entry_id]["storage"]
                if storage.get_code(code_id):
                    entry_id = check_entry_id
                    _LOGGER.debug("Found code %s in entry %s", code_id, entry_id)
                    break

        if not entry_id:
            raise ServiceValidationError(
                f"Could not find code {code_id} in any OpenIRBlaster device",
                translation_domain=DOMAIN,
                translation_key="code_not_found",
            )

        if entry_id not in hass.data[DOMAIN]:
            raise ServiceValidationError(
                f"Config entry {entry_id} not found",
                translation_domain=DOMAIN,
                translation_key="config_entry_not_found",
            )

        storage: OpenIRBlasterStorage = hass.data[DOMAIN][entry_id]["storage"]
        success = await storage.async_delete_code(code_id)

        if success:
            _LOGGER.info("Deleted code %s", code_id)
            # Reload entry to remove button entity
            await hass.config_entries.async_reload(entry_id)
        else:
            raise ServiceValidationError(
                f"Code {code_id} not found in storage",
                translation_domain=DOMAIN,
                translation_key="code_not_found",
            )

    async def handle_rename_code(call: ServiceCall) -> None:
        """Handle rename_code service call."""
        entry_id = call.data["config_entry_id"]
        code_id = call.data[ATTR_CODE_ID]
        new_name = call.data["new_name"]

        if entry_id not in hass.data[DOMAIN]:
            raise ServiceValidationError(
                f"Config entry {entry_id} not found",
                translation_domain=DOMAIN,
                translation_key="config_entry_not_found",
            )

        storage: OpenIRBlasterStorage = hass.data[DOMAIN][entry_id]["storage"]
        code = await storage.async_update_code(code_id, name=new_name)

        if code:
            _LOGGER.info("Renamed code %s to %s", code_id, new_name)
            # Reload entry to update button entity name
            await hass.config_entries.async_reload(entry_id)
        else:
            raise ServiceValidationError(
                f"Code {code_id} not found",
                translation_domain=DOMAIN,
                translation_key="code_not_found",
            )

    async def handle_save_pending(call: ServiceCall) -> None:
        """Handle save_pending service call - saves the pending learned code."""
        entry_id = call.data["config_entry_id"]
        name = call.data["name"]
        tags_str = call.data.get("tags", "")
        notes = call.data.get("notes", "")

        if entry_id not in hass.data[DOMAIN]:
            raise ServiceValidationError(
                f"Config entry {entry_id} not found",
                translation_domain=DOMAIN,
                translation_key="config_entry_not_found",
            )

        learning_session: LearningSession = hass.data[DOMAIN][entry_id]["learning_session"]
        storage: OpenIRBlasterStorage = hass.data[DOMAIN][entry_id]["storage"]

        # Check if there's a pending code
        if not learning_session.pending_code:
            raise ServiceValidationError(
                "No pending code to save. Learn a code first.",
                translation_domain=DOMAIN,
                translation_key="no_pending_code",
            )

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
