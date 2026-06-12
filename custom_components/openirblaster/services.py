"""Services for OpenIRBlaster integration."""

from __future__ import annotations

import asyncio
import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import (
    HomeAssistantError,
    ServiceNotFound,
    ServiceValidationError,
)
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .const import (
    ATTR_CARRIER_HZ,
    ATTR_CODE_ID,
    ATTR_CODE_NAME,
    ATTR_PULSES,
    DOMAIN,
    SERVICE_DELETE_CODE,
    SERVICE_LEARN_CANCEL,
    SERVICE_LEARN_START,
    SERVICE_RENAME_CODE,
    SERVICE_SAVE_PENDING,
    SERVICE_SEND_CODE,
    SIGNAL_CODE_ADDED,
    SIGNAL_CODE_RENAMED,
    STATE_ARMED,
    STATE_CANCELLED,
    STATE_RECEIVED,
    STATE_TIMEOUT,
)
from .data import OpenIRBlasterData
from .helpers import (
    async_clear_send_service_missing,
    async_flag_send_service_missing,
    async_remove_code_entities,
    get_esphome_service,
)
from .learning import LearnedCode

_LOGGER = logging.getLogger(__name__)

# Session states that resolve a response-mode learn_start call
_TERMINAL_STATES = {STATE_RECEIVED, STATE_TIMEOUT, STATE_CANCELLED}

# Service schema definitions
LEARN_START_SCHEMA = vol.Schema(
    {
        vol.Required("config_entry_id"): cv.string,
        vol.Optional("timeout", default=30): cv.positive_int,
    }
)

LEARN_CANCEL_SCHEMA = vol.Schema(
    {
        vol.Required("config_entry_id"): cv.string,
        vol.Optional("discard_pending", default=False): cv.boolean,
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

    async def handle_learn_start(call: ServiceCall) -> ServiceResponse:
        """Handle learn_start service call.

        Without return_response this is fire-and-forget. With it, the call
        blocks until the session outcome (capture, timeout, or cancel) and
        returns it, so scripts can start learning and get the captured
        code's metadata back in one call.
        """
        entry_id = call.data["config_entry_id"]
        timeout = call.data.get("timeout", 30)

        data = _async_get_entry_data(hass, entry_id)
        learning_session = data.learning_session

        if not call.return_response:
            # Per-session override only; must not mutate the session
            # default, which would stick for all subsequent sessions.
            success = await learning_session.async_start_learning(timeout=timeout)
            if not success:
                raise HomeAssistantError(
                    f"Failed to start learning session for entry {entry_id}"
                )
            _LOGGER.info("Learning session started for entry %s", entry_id)
            return None

        # Response requested: register for the outcome before starting so a
        # fast capture cannot slip between start and subscription.
        loop = asyncio.get_running_loop()
        outcome: asyncio.Future[tuple[str, LearnedCode | None]] = loop.create_future()

        def _capture_outcome(state: str, code: LearnedCode | None) -> None:
            if state in _TERMINAL_STATES and not outcome.done():
                outcome.set_result((state, code))

        learning_session.register_callback(_capture_outcome)
        try:
            success = await learning_session.async_start_learning(timeout=timeout)
            if not success:
                raise HomeAssistantError(
                    f"Failed to start learning session for entry {entry_id}"
                )
            _LOGGER.info(
                "Learning session started for entry %s (awaiting outcome)",
                entry_id,
            )
            try:
                # Small margin past the session's own timeout: the TIMEOUT
                # state should normally arrive through the callback.
                state, code = await asyncio.wait_for(outcome, timeout=timeout + 5)
            except TimeoutError:
                return {"status": "timeout"}
        finally:
            learning_session.unregister_callback(_capture_outcome)

        if state == STATE_RECEIVED and code is not None:
            return {
                "status": "received",
                "carrier_hz": code.carrier_hz,
                "pulse_count": len(code.pulses),
                "timestamp": code.timestamp,
            }
        return {"status": "timeout" if state == STATE_TIMEOUT else "cancelled"}

    async def handle_learn_cancel(call: ServiceCall) -> None:
        """Handle learn_cancel service call.

        Cancels an ARMED session (switch off, listeners cleaned) and resets
        the session to IDLE. A pending unsaved code is only discarded when
        discard_pending is true; otherwise the call is rejected so a
        captured code cannot be destroyed by accident.
        """
        entry_id = call.data["config_entry_id"]
        discard_pending = call.data["discard_pending"]

        data = _async_get_entry_data(hass, entry_id)
        learning_session = data.learning_session

        if learning_session.state == STATE_ARMED:
            await learning_session.async_cancel_learning()

        # Checked AFTER the cancel attempt: a capture can commit while the
        # session still reads ARMED (finalize suspended on the network
        # switch turn-off). The cancel above is a no-op in that window, and
        # the captured code must never be destroyed without an explicit
        # discard_pending. This single check also covers the plain
        # RECEIVED-with-pending case.
        if not discard_pending and learning_session.pending_code is not None:
            raise ServiceValidationError(
                "A learned code is pending save; pass discard_pending to "
                "drop it",
                translation_domain=DOMAIN,
                translation_key="pending_code_unsaved",
            )

        # Reset to IDLE (clears a discarded pending code and dismisses any
        # stale session notifications).
        await learning_session.async_clear_pending()
        _LOGGER.info("Learning session cancelled for entry %s", entry_id)

    async def handle_send_code(call: ServiceCall) -> ServiceResponse:
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

        if call.return_response:
            return {
                "code_id": code_id,
                "name": code.get(ATTR_CODE_NAME) if code else None,
                "carrier_hz": carrier_hz,
                "pulse_count": len(pulses) if pulses else 0,
                "sent": True,
            }
        return None

    async def handle_delete_code(call: ServiceCall) -> None:
        """Handle delete_code service call."""
        code_id = call.data[ATTR_CODE_ID]
        entry_id = call.data.get("config_entry_id")

        # If no config_entry_id provided, find it by searching for the code.
        # With multiple blasters the same code_id can exist on several
        # entries; deleting from "the first match" could hit the wrong
        # device, so ambiguity is rejected instead.
        if not entry_id:
            _LOGGER.debug("No config_entry_id provided, searching for code %s", code_id)
            matches = [
                candidate.entry_id
                for candidate in hass.config_entries.async_entries(DOMAIN)
                if candidate.state is ConfigEntryState.LOADED
                and candidate.runtime_data.storage.get_code(code_id)
            ]
            if len(matches) > 1:
                raise ServiceValidationError(
                    f"Code {code_id} exists on multiple devices; pass "
                    "config_entry_id to disambiguate",
                    translation_domain=DOMAIN,
                    translation_key="code_id_ambiguous",
                    translation_placeholders={"code_id": code_id},
                )
            if matches:
                entry_id = matches[0]
                _LOGGER.debug("Found code %s in entry %s", code_id, entry_id)

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
            # Remove the code's button entities from the entity registry.
            # Removing the registry entry of a live entity also removes the
            # entity object from HA, so no reload is needed.
            async_remove_code_entities(hass, entry_id, code_id)
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
            # The code_id is stable, so the entity survives; tell the live
            # CodeButton to update its name in place (no reload).
            async_dispatcher_send(
                hass,
                SIGNAL_CODE_RENAMED.format(entry_id=entry_id),
                code_id,
                new_name,
            )
        else:
            raise ServiceValidationError(
                f"Code {code_id} not found",
                translation_domain=DOMAIN,
                translation_key="code_not_found",
                translation_placeholders={"code_id": code_id},
            )

    async def handle_save_pending(call: ServiceCall) -> ServiceResponse:
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
        saved_code = await storage.async_add_code(
            name=name,
            carrier_hz=pending.carrier_hz,
            pulses=pending.pulses,
            tags=tags,
            notes=notes,
        )

        # Persist last-learned metadata so the sensors survive HA restarts.
        await storage.async_set_last_learned(
            name=name,
            timestamp=pending.timestamp,
            pulse_count=len(pending.pulses),
        )
        data.last_learned_name = name
        data.last_learned_timestamp = pending.timestamp
        data.last_learned_pulse_count = len(pending.pulses)

        _LOGGER.info("Saved pending code as: %s", name)

        # Clear pending code (resets the session to IDLE).
        await learning_session.async_clear_pending()

        # Add the new code button dynamically and refresh the last-learned
        # sensors (no entry reload; the learning session stays alive).
        async_dispatcher_send(
            hass,
            SIGNAL_CODE_ADDED.format(entry_id=entry_id),
            saved_code,
        )

        if call.return_response:
            return {
                "code_id": saved_code[ATTR_CODE_ID],
                "name": saved_code[ATTR_CODE_NAME],
                "carrier_hz": saved_code[ATTR_CARRIER_HZ],
                "pulse_count": len(saved_code[ATTR_PULSES]),
            }
        return None

    # Register services
    hass.services.async_register(
        DOMAIN,
        SERVICE_LEARN_START,
        handle_learn_start,
        schema=LEARN_START_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_LEARN_CANCEL, handle_learn_cancel, schema=LEARN_CANCEL_SCHEMA
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SEND_CODE,
        handle_send_code,
        schema=SEND_CODE_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_DELETE_CODE, handle_delete_code, schema=DELETE_CODE_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_RENAME_CODE, handle_rename_code, schema=RENAME_CODE_SCHEMA
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SAVE_PENDING,
        handle_save_pending,
        schema=SAVE_PENDING_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
