"""Bridge stored IR codes onto Home Assistant's infrared platform.

This is what makes OpenIRBlaster pluckable. HAIR asks an integration to
replay a stored code through a caller-chosen emitter; if that emitter is
HAIR's own observer entity, HAIR captures the code instead of putting it
on the air, and the user keeps codes they already learned.

Everything here is imported lazily, on the first call rather than at
module import. The `infrared` domain arrived in Home Assistant 2026.4 and
this integration still supports 2024.12, so importing it at module level
would break setup for every user on an older core. A user who never calls
the pluck service never loads any of it.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from homeassistant.exceptions import HomeAssistantError

if TYPE_CHECKING:
    from homeassistant.core import Context, HomeAssistant

_LOGGER = logging.getLogger(__name__)

# The carrier used when a stored code has none recorded. Captures made
# through the infrared platform do not carry one, because ESPHome reports
# no modulation over ir_rf_proxy.
DEFAULT_CARRIER_HZ = 38000

# Built on first use, then reused. The base class lives in a dependency
# we cannot import at module scope, so the subclass cannot be declared
# at module scope either.
_RAW_COMMAND_CLASS: type | None = None


def _import_infrared() -> tuple[Any, Any]:
    """Return (async_send_command, InfraredCommand) from the infrared domain.

    InfraredCommand is re-exported by the component on every version that
    has it, which matters because the underlying library moved the class
    between releases: infrared_protocols 1.x exported Command at the top
    level and 10.x only exports it from infrared_protocols.commands.
    Going through the component sidesteps that entirely.
    """
    try:
        from homeassistant.components.infrared import (  # noqa: PLC0415
            InfraredCommand,
            async_send_command,
        )
    except ImportError as err:
        raise HomeAssistantError(
            "This action needs Home Assistant's infrared platform, which "
            "arrived in 2026.4. Upgrade Home Assistant, or use the standalone "
            "export script instead."
        ) from err

    return async_send_command, InfraredCommand


def _raw_command_class() -> type:
    """Build (once) a Command subclass that replays stored timings verbatim.

    get_raw_timings returns signed microseconds, positive for mark and
    negative for space, which is both the stored OpenIRBlaster convention
    and what the platform has expected since 2026.5. No conversion is
    needed and none is done, so what was captured is what is sent.
    """
    global _RAW_COMMAND_CLASS  # noqa: PLW0603

    if _RAW_COMMAND_CLASS is not None:
        return _RAW_COMMAND_CLASS

    _, infrared_command = _import_infrared()

    class RawCommand(infrared_command):  # type: ignore[misc, valid-type]
        """A stored pulse array, replayed exactly as it was captured."""

        def __init__(
            self,
            timings: list[int],
            *,
            modulation: int | None = None,
            repeat_count: int = 0,
        ) -> None:
            super().__init__(
                modulation=modulation or DEFAULT_CARRIER_HZ,
                repeat_count=repeat_count,
            )
            self._timings = list(timings)

        def get_raw_timings(self) -> list[int]:
            """Signed microseconds, positive mark and negative space."""
            return list(self._timings)

    _RAW_COMMAND_CLASS = RawCommand
    return RawCommand


def build_command(pulses: list[int], carrier_hz: int | None = None) -> Any:
    """Build an infrared platform Command from a stored code."""
    if not pulses:
        raise HomeAssistantError("The stored code has no pulse data")
    return _raw_command_class()(pulses, modulation=carrier_hz)


async def async_send_stored_code(
    hass: HomeAssistant,
    emitter_entity_id: str,
    pulses: list[int],
    carrier_hz: int | None = None,
    context: Context | None = None,
) -> None:
    """Send a stored code through a named infrared emitter, and wait for it.

    The await matters. HAIR captures the command inside this call, so
    returning before the send completes would make a pluck racy.
    """
    async_send_command, _ = _import_infrared()
    command = build_command(pulses, carrier_hz)

    _LOGGER.debug(
        "Sending %d timings at %s Hz to %s",
        len(pulses),
        carrier_hz or DEFAULT_CARRIER_HZ,
        emitter_entity_id,
    )
    await async_send_command(hass, emitter_entity_id, command, context=context)
