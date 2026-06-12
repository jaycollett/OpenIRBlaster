"""Services for OpenIRBlaster integration."""

from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import (
    HomeAssistantError,
    ServiceNotFound,
    ServiceValidationError,
)
from homeassistant.helpers import config_validation as cv

from .const import (
    ATTR_CARRIER_HZ,
    ATTR_CODE_ID,
    ATTR_PULSES,
    DOMAIN,
    SERVICE_DELETE_CODE,
    SERVICE_LEARN_START,
    SERVICE_RENAME_CODE,
    SERVICE_SAVE_PENDING,
    SERVICE_SEND_CODE,
)
from .data import OpenIRBlasterData
from .helpers import (
    async_clear_send_service_missing,
    async_flag_send_service_missing,
    async_remove_code_entities,
    get_esphome_service,
)

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


def _async_get_entry_data(hass: HomeAssistant, entry_id: str) -> OpenIRBlasterData:
    """Resolve a config_entry_id to its loaded runtime data.

    Raises ServiceValidationError when the entry does not exist (or belongs
    to another integration) or is not currently loaded.
    """
    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None or entry.domain != DOMAIN:
        raise ServiceValidationError(
            f"Config entry {entry_id} not found",
            translation_domain=DOMAIN,
            translation_key="config_entry_not_found",
            translation_placeholders={"config_entry_id": entry_id},
        )
    if entry.state is not ConfigEntryState.LOADED:
        raise ServiceValidationError(
            f"Config entry {entry_id} is not loaded",
            translation_domain=DOMAIN,
            translation_key="config_entry_not_loaded",
            translation_placeholders={"config_entry_id": entry_id},
        )
    return entry.runtime_data


async def async_setup_services(hass: HomeAssistant) -> None:
    """Set up services for OpenIRBlaster."""
    _LOGGER.info("Setting up OpenIRBlaster services")

    async def handle_learn_start(call: ServiceCall) -> None:
        """Handle learn_start service call."""
        entry_id = call.data["config_entry_id"]
        timeout = call.data.get("timeout", 30)

        data = _async_get_entry_data(hass, entry_id)

        # Per-session override only; must not mutate the session default,
        # which would silently stick for all subsequent sessions.
        success = await data.learning_session.async_start_learning(timeout=timeout)

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

        data = _async_get_entry_data(hass, entry_id)
        storage = data.storage

        # Get code from storage or use overrides
        code = storage.get_code(code_id)
        if code is None and (
            ATTR_CARRIER_HZ not in call.data or ATTR_PULSES not in call.data
        ):
            raise ServiceValidationError(
                f"Code {code_id} not found and no override provided",
                translation_domain=DOMAIN,
                translation_key="code_not_found",
                translation_placeholders={"code_id": code_id},
            )

        carrier_hz = call.data.get(ATTR_CARRIER_HZ, code.get(ATTR_CARRIER_HZ) if code else None)
        pulses = call.data.get(ATTR_PULSES, code.get(ATTR_PULSES) if code else None)

        # Call ESPHome service (discovered at integration load time)
        service_name = get_esphome_service(hass, entry_id)
        if not service_name:
            async_flag_send_service_missing(hass, entry_id)
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
            async_clear_send_service_missing(hass, entry_id)
        except ServiceNotFound as err:
            # The service disappeared after setup (device renamed/offline).
            async_flag_send_service_missing(hass, entry_id)
            raise HomeAssistantError(
                f"Failed to send code {code_id}: {err}"
            ) from err
        except Exception as err:
            raise HomeAssistantError(f"Failed to send code {code_id}: {err}") from err

    async def handle_delete_code(call: ServiceCall) -> None:
        """Handle delete_code service call."""
        code_id = call.data[ATTR_CODE_ID]
        entry_id = call.data.get("config_entry_id")

        # If no config_entry_id provided, find it by searching for the code
        if not entry_id:
            _LOGGER.debug("No config_entry_id provided, searching for code %s", code_id)
            for candidate in hass.config_entries.async_entries(DOMAIN):
                if candidate.state is not ConfigEntryState.LOADED:
                    continue
                if candidate.runtime_data.storage.get_code(code_id):
                    entry_id = candidate.entry_id
                    _LOGGER.debug("Found code %s in entry %s", code_id, entry_id)
                    break

        if not entry_id:
            raise ServiceValidationError(
                f"Could not find code {code_id} in any OpenIRBlaster device",
                translation_domain=DOMAIN,
                translation_key="code_not_found",
                translation_placeholders={"code_id": code_id},
            )

        data = _async_get_entry_data(hass, entry_id)
        success = await data.storage.async_delete_code(code_id)

        if success:
            _LOGGER.info("Deleted code %s", code_id)
            # Remove the code's button entities from the entity registry,
            # then reload the entry. Without the registry cleanup the
            # buttons linger as "no longer provided" orphans.
            async_remove_code_entities(hass, entry_id, code_id)
            await hass.config_entries.async_reload(entry_id)
        else:
            raise ServiceValidationError(
                f"Code {code_id} not found in storage",
                translation_domain=DOMAIN,
                translation_key="code_not_found",
                translation_placeholders={"code_id": code_id},
            )

    async def handle_rename_code(call: ServiceCall) -> None:
        """Handle rename_code service call."""
        entry_id = call.data["config_entry_id"]
        code_id = call.data[ATTR_CODE_ID]
        new_name = call.data["new_name"]

        data = _async_get_entry_data(hass, entry_id)
        code = await data.storage.async_update_code(code_id, name=new_name)

        if code:
            _LOGGER.info("Renamed code %s to %s", code_id, new_name)
            # Reload entry to update button entity name
            await hass.config_entries.async_reload(entry_id)
        else:
            raise ServiceValidationError(
                f"Code {code_id} not found",
                translation_domain=DOMAIN,
                translation_key="code_not_found",
                translation_placeholders={"code_id": code_id},
            )

    async def handle_save_pending(call: ServiceCall) -> None:
        """Handle save_pending service call - saves the pending learned code."""
        entry_id = call.data["config_entry_id"]
        name = call.data["name"]
        tags_str = call.data.get("tags", "")
        notes = call.data.get("notes", "")

        data = _async_get_entry_data(hass, entry_id)
        learning_session = data.learning_session
        storage = data.storage

        # Check if there's a pending code
        if not learning_session.pending_code:
            raise ServiceValidationError(
                "No pending code to save. Learn a code first.",
                translation_domain=DOMAIN,
                translation_key="no_pending_code",
            )

        # Reject duplicate names (same check as the Learn button path)
        if storage.name_exists(name):
            raise ServiceValidationError(
                f"A code named {name} already exists",
                translation_domain=DOMAIN,
                translation_key="name_exists",
                translation_placeholders={"name": name},
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

        # Persist last-learned metadata so the sensors survive the reload
        # below and HA restarts.
        await storage.async_set_last_learned(
            name=name,
            timestamp=pending.timestamp,
            pulse_count=len(pending.pulses),
        )
        data.last_learned_name = name
        data.last_learned_timestamp = pending.timestamp
        data.last_learned_pulse_count = len(pending.pulses)

        _LOGGER.info("Saved pending code as: %s", name)

        # Clear pending code before reloading so the session teardown does
        # not race the reload's cleanup of the same session.
        await learning_session.async_clear_pending()

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
