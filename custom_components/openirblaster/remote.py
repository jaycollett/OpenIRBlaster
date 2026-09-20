"""Remote platform for OpenIRBlaster.

One remote entity per device, for two reasons.

It gives the stored library a standard Home Assistant surface:
remote.send_command with a code name does what the per-code buttons do,
which is useful in scripts that already speak the remote domain.

It also makes the device discoverable as a pluckable blaster. HAIR's
Add Blaster dialog offers remote.* entities that advertise
RemoteEntityFeature.LEARN_COMMAND, and the send_learned_ir_command
action registered here is the one HAIR calls to replay a stored code
through an emitter it controls. See docs/pluckable.md.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.components.remote import (
    ATTR_COMMAND,
    ATTR_DEVICE,
    RemoteEntity,
    RemoteEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_platform
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .commands import async_send_stored_code
from .const import (
    ATTR_CARRIER_HZ,
    ATTR_CODE_NAME,
    ATTR_PULSES,
    CONF_DEVICE_ID,
    CONF_MAC_ADDRESS,
    DOMAIN,
    SERVICE_SEND_LEARNED_IR_COMMAND,
    UNIQUE_ID_REMOTE,
)
from .data import OpenIRBlasterConfigEntry

_LOGGER = logging.getLogger(__name__)

# Push-based integration: no parallel polling coordination needed
PARALLEL_UPDATES = 0

SEND_LEARNED_IR_COMMAND_SCHEMA = {
    vol.Required(ATTR_COMMAND): cv.string,
    vol.Required("emitter_entity_id"): cv.entity_id,
    # Accepted and ignored. The OpenIRBlaster library is flat, with no
    # appliance grouping, but HAIR always sends this field and rejecting
    # it would fail every pluck.
    vol.Optional(ATTR_DEVICE): vol.Any(cv.string, None),
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: OpenIRBlasterConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the OpenIRBlaster remote entity."""
    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        SERVICE_SEND_LEARNED_IR_COMMAND,
        SEND_LEARNED_IR_COMMAND_SCHEMA,
        "async_send_learned_ir_command",
    )

    async_add_entities([OpenIRBlasterRemote(entry)])


class OpenIRBlasterRemote(RemoteEntity):
    """The stored code library, as a remote entity."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "remote"
    _attr_assumed_state = True
    # LEARN_COMMAND advertises that this entity holds learned codes. HAIR
    # filters its blaster picker on it.
    _attr_supported_features = RemoteEntityFeature.LEARN_COMMAND

    def __init__(self, entry: OpenIRBlasterConfigEntry) -> None:
        """Initialize the remote."""
        self._entry = entry
        self._attr_unique_id = UNIQUE_ID_REMOTE.format(entry_id=entry.entry_id)

        device_id = entry.data[CONF_DEVICE_ID]
        mac_address = entry.data.get(CONF_MAC_ADDRESS)
        if mac_address:
            base_identifier = mac_address.lower().replace(":", "")
        else:
            base_identifier = device_id

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, base_identifier)},
        )

    @property
    def is_on(self) -> bool:
        """The library is always available while the entry is loaded."""
        return True

    def _find_code(self, name: str) -> dict[str, Any]:
        """Look up a stored code by the name it was learned under.

        Name rather than id, because a name is what a user recognises and
        can type, and it is what HAIR's pluck dialog collects. Matching is
        case-insensitive and ignores surrounding whitespace. The id is
        accepted as a fallback so existing scripts keep working.
        """
        storage = self._entry.runtime_data.storage
        wanted = name.strip().lower()

        for code in storage.get_codes():
            if str(code.get(ATTR_CODE_NAME, "")).strip().lower() == wanted:
                return code

        code = storage.get_code(name.strip())
        if code is not None:
            return code

        known = ", ".join(
            str(c.get(ATTR_CODE_NAME)) for c in storage.get_codes()
        )
        raise ServiceValidationError(
            f"No stored code named {name!r}. "
            f"Known codes: {known or 'none yet'}",
            translation_domain=DOMAIN,
            translation_key="code_name_not_found",
            translation_placeholders={"name": name},
        )

    async def async_send_learned_ir_command(
        self,
        command: str,
        emitter_entity_id: str,
        device: str | None = None,
    ) -> None:
        """Replay a stored code through a caller-chosen infrared emitter.

        Point emitter_entity_id at an emitter on your own hardware and the
        code goes on the air as usual. Point it at HAIR's observer entity
        and HAIR captures the code instead, which is how a user moves a
        library across without re-learning anything.

        The send is awaited all the way through so the command is
        delivered before this returns.
        """
        if device:
            _LOGGER.debug(
                "Ignoring appliance %r; the OpenIRBlaster library is flat",
                device,
            )

        code = self._find_code(command)
        await async_send_stored_code(
            self.hass,
            emitter_entity_id,
            code.get(ATTR_PULSES) or [],
            code.get(ATTR_CARRIER_HZ),
            context=self._context,
        )
        _LOGGER.info(
            "Replayed %r through %s", code.get(ATTR_CODE_NAME), emitter_entity_id
        )

    async def async_send_command(self, command: list[str], **kwargs: Any) -> None:
        """Send one or more stored codes through this device's own hardware.

        The ordinary remote.send_command path. Unchanged behaviour: codes
        go out through the ESPHome service as they always have.
        """
        from .button import async_send_code_via_esphome

        for name in command:
            code = self._find_code(name)
            await async_send_code_via_esphome(
                self.hass,
                self._entry.entry_id,
                code.get(ATTR_CARRIER_HZ),
                code.get(ATTR_PULSES) or [],
                label=str(code.get(ATTR_CODE_NAME)),
            )

    async def async_turn_on(self, **kwargs: Any) -> None:
        """No-op. The library has no power state."""

    async def async_turn_off(self, **kwargs: Any) -> None:
        """No-op. The library has no power state."""
