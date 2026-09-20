"""Tests for the remote platform and the pluckable contract.

The pluckable contract is HAIR's, documented at
docs/making-your-integration-pluckable.md in its repository. The four
numbered requirements are each pinned by a test below, because the whole
point of the contract is that a third party can rely on it.

Home Assistant's infrared domain cannot be imported in this test
environment (it needs infrared_protocols, which requires Python 3.14 and
is not a test dependency), so these tests install a stand-in module. That
is enough to prove our side of the contract: which emitter we target,
what Command we build, and that we await the send.
"""

from __future__ import annotations

import sys
import types
from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.components.remote import RemoteEntityFeature
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from custom_components.openirblaster import commands as oib_commands
from custom_components.openirblaster.const import (
    DOMAIN,
    SERVICE_SEND_LEARNED_IR_COMMAND,
)

PULSES = [9000, -4500, 560, -560, 560, -1690, 560, -39000]


class _FakeCommand:
    """Stand-in for infrared_protocols.commands.Command."""

    def __init__(self, *, modulation: int, repeat_count: int = 0) -> None:
        self.modulation = modulation
        self.repeat_count = repeat_count


@pytest.fixture
def fake_infrared():
    """Install a stand-in homeassistant.components.infrared."""
    module = types.ModuleType("homeassistant.components.infrared")
    module.InfraredCommand = _FakeCommand
    module.async_send_command = AsyncMock()

    original = sys.modules.get("homeassistant.components.infrared")
    sys.modules["homeassistant.components.infrared"] = module
    # commands.py caches the generated subclass, so it has to be dropped
    # or a later test reuses a class bound to a stale base.
    oib_commands._RAW_COMMAND_CLASS = None
    try:
        yield module
    finally:
        if original is not None:
            sys.modules["homeassistant.components.infrared"] = original
        else:
            sys.modules.pop("homeassistant.components.infrared", None)
        oib_commands._RAW_COMMAND_CLASS = None


async def _setup_with_remote(
    hass: HomeAssistant, data: dict, codes: list[tuple[str, int]]
) -> MockConfigEntry:
    """Load an entry with only the remote platform, holding the given codes."""
    entry = MockConfigEntry(domain=DOMAIN, data=data, title="Living Room Blaster")
    entry.add_to_hass(hass)

    with patch(
        "custom_components.openirblaster.PLATFORMS", [Platform.REMOTE]
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    for name, carrier in codes:
        await entry.runtime_data.storage.async_add_code(
            name=name, carrier_hz=carrier, pulses=list(PULSES)
        )
    return entry


def _remote_entity_id(hass: HomeAssistant) -> str:
    ids = [e for e in hass.states.async_entity_ids("remote")]
    assert ids, "no remote entity was created"
    return ids[0]


# --- Discovery -------------------------------------------------------


async def test_remote_entity_created(
    hass: HomeAssistant, mock_config_entry_data: dict
) -> None:
    await _setup_with_remote(hass, mock_config_entry_data, [])
    assert _remote_entity_id(hass)


async def test_remote_advertises_learn_command(
    hass: HomeAssistant, mock_config_entry_data: dict
) -> None:
    """HAIR filters its blaster picker on LEARN_COMMAND.

    Without this feature bit the device is never offered as something to
    pluck from, so this is what makes the integration discoverable.
    """
    await _setup_with_remote(hass, mock_config_entry_data, [])

    state = hass.states.get(_remote_entity_id(hass))
    features = RemoteEntityFeature(state.attributes["supported_features"])

    assert RemoteEntityFeature.LEARN_COMMAND in features


async def test_pluck_service_registered(
    hass: HomeAssistant, mock_config_entry_data: dict
) -> None:
    await _setup_with_remote(hass, mock_config_entry_data, [])
    assert hass.services.has_service(DOMAIN, SERVICE_SEND_LEARNED_IR_COMMAND)


# --- The four contract requirements ----------------------------------


async def test_contract_1_replays_a_stored_code_by_name(
    hass: HomeAssistant, mock_config_entry_data: dict, fake_infrared
) -> None:
    """Requirement 1: address the code by the name it was learned under."""
    await _setup_with_remote(hass, mock_config_entry_data, [("TV Power", 38000)])

    await hass.services.async_call(
        DOMAIN,
        SERVICE_SEND_LEARNED_IR_COMMAND,
        {
            "entity_id": _remote_entity_id(hass),
            "command": "TV Power",
            "emitter_entity_id": "infrared.hair_tweezer",
        },
        blocking=True,
    )

    assert fake_infrared.async_send_command.await_count == 1


async def test_contract_2_targets_the_caller_chosen_emitter(
    hass: HomeAssistant, mock_config_entry_data: dict, fake_infrared
) -> None:
    """Requirement 2: the code goes to the emitter the caller names.

    This single parameter is what makes the integration pluckable. If the
    code could only ever leave through our own hardware, HAIR could never
    catch it.
    """
    await _setup_with_remote(hass, mock_config_entry_data, [("TV Power", 38000)])

    for target in ("infrared.hair_tweezer", "infrared.living_room_blaster_tx"):
        fake_infrared.async_send_command.reset_mock()
        await hass.services.async_call(
            DOMAIN,
            SERVICE_SEND_LEARNED_IR_COMMAND,
            {
                "entity_id": _remote_entity_id(hass),
                "command": "TV Power",
                "emitter_entity_id": target,
            },
            blocking=True,
        )

        args = fake_infrared.async_send_command.await_args.args
        assert args[1] == target, f"sent to {args[1]!r}, expected {target!r}"


async def test_contract_3_builds_a_real_platform_command(
    hass: HomeAssistant, mock_config_entry_data: dict, fake_infrared
) -> None:
    """Requirement 3: build a real Command carrying the stored code.

    Also pins that the carrier survives, since a code learned at 36 kHz
    has to arrive at HAIR as a 36 kHz code.
    """
    await _setup_with_remote(hass, mock_config_entry_data, [("TV Mute", 36000)])

    await hass.services.async_call(
        DOMAIN,
        SERVICE_SEND_LEARNED_IR_COMMAND,
        {
            "entity_id": _remote_entity_id(hass),
            "command": "TV Mute",
            "emitter_entity_id": "infrared.hair_tweezer",
        },
        blocking=True,
    )

    command = fake_infrared.async_send_command.await_args.args[2]

    assert isinstance(command, _FakeCommand)
    assert command.modulation == 36000
    # Signed microseconds, positive mark and negative space, exactly as
    # captured. No re-encoding.
    assert command.get_raw_timings() == PULSES


async def test_contract_4_awaits_the_full_send(
    hass: HomeAssistant, mock_config_entry_data: dict, fake_infrared
) -> None:
    """Requirement 4: the send is awaited, so a pluck cannot race.

    HAIR captures inside the await. If the service scheduled the send and
    returned, HAIR could look for the signal before it arrived.
    """
    await _setup_with_remote(hass, mock_config_entry_data, [("TV Power", 38000)])

    finished = False

    async def _slow_send(*args, **kwargs):
        nonlocal finished
        finished = True

    fake_infrared.async_send_command.side_effect = _slow_send

    await hass.services.async_call(
        DOMAIN,
        SERVICE_SEND_LEARNED_IR_COMMAND,
        {
            "entity_id": _remote_entity_id(hass),
            "command": "TV Power",
            "emitter_entity_id": "infrared.hair_tweezer",
        },
        blocking=True,
    )

    assert finished, "service returned before the send completed"


# --- Behaviour around the contract -----------------------------------


async def test_carrierless_code_defaults_to_38khz(
    hass: HomeAssistant, mock_config_entry_data: dict, fake_infrared
) -> None:
    entry = await _setup_with_remote(hass, mock_config_entry_data, [])
    await entry.runtime_data.storage.async_add_code(
        name="No Carrier", carrier_hz=None, pulses=list(PULSES)
    )

    await hass.services.async_call(
        DOMAIN,
        SERVICE_SEND_LEARNED_IR_COMMAND,
        {
            "entity_id": _remote_entity_id(hass),
            "command": "No Carrier",
            "emitter_entity_id": "infrared.hair_tweezer",
        },
        blocking=True,
    )

    assert fake_infrared.async_send_command.await_args.args[2].modulation == 38000


async def test_name_match_is_case_and_space_insensitive(
    hass: HomeAssistant, mock_config_entry_data: dict, fake_infrared
) -> None:
    """A user typing into HAIR's pluck dialog should not have to be exact."""
    await _setup_with_remote(hass, mock_config_entry_data, [("TV Power", 38000)])

    await hass.services.async_call(
        DOMAIN,
        SERVICE_SEND_LEARNED_IR_COMMAND,
        {
            "entity_id": _remote_entity_id(hass),
            "command": "  tv power  ",
            "emitter_entity_id": "infrared.hair_tweezer",
        },
        blocking=True,
    )

    assert fake_infrared.async_send_command.await_count == 1


async def test_appliance_field_is_accepted_and_ignored(
    hass: HomeAssistant, mock_config_entry_data: dict, fake_infrared
) -> None:
    """HAIR always sends `device`; rejecting it would fail every pluck.

    The OpenIRBlaster library is flat, so there is nothing to group by,
    but the field has to be tolerated.
    """
    await _setup_with_remote(hass, mock_config_entry_data, [("TV Power", 38000)])

    await hass.services.async_call(
        DOMAIN,
        SERVICE_SEND_LEARNED_IR_COMMAND,
        {
            "entity_id": _remote_entity_id(hass),
            "command": "TV Power",
            "emitter_entity_id": "infrared.hair_tweezer",
            "device": "living room",
        },
        blocking=True,
    )

    assert fake_infrared.async_send_command.await_count == 1


async def test_unknown_code_raises_a_readable_error(
    hass: HomeAssistant, mock_config_entry_data: dict, fake_infrared
) -> None:
    """HAIR surfaces our message to the user, so it has to be readable."""
    await _setup_with_remote(hass, mock_config_entry_data, [("TV Power", 38000)])

    with pytest.raises(ServiceValidationError) as excinfo:
        await hass.services.async_call(
            DOMAIN,
            SERVICE_SEND_LEARNED_IR_COMMAND,
            {
                "entity_id": _remote_entity_id(hass),
                "command": "Nope",
                "emitter_entity_id": "infrared.hair_tweezer",
            },
            blocking=True,
        )

    assert "Nope" in str(excinfo.value)
    assert "TV Power" in str(excinfo.value), "should list what is available"


async def test_missing_infrared_platform_explains_itself(
    hass: HomeAssistant, mock_config_entry_data: dict
) -> None:
    """On a core with no infrared domain, say so instead of failing oddly."""
    await _setup_with_remote(hass, mock_config_entry_data, [("TV Power", 38000)])
    oib_commands._RAW_COMMAND_CLASS = None

    with patch.dict(sys.modules, {"homeassistant.components.infrared": None}):
        with pytest.raises(HomeAssistantError) as excinfo:
            await hass.services.async_call(
                DOMAIN,
                SERVICE_SEND_LEARNED_IR_COMMAND,
                {
                    "entity_id": _remote_entity_id(hass),
                    "command": "TV Power",
                    "emitter_entity_id": "infrared.hair_tweezer",
                },
                blocking=True,
            )

    assert "2026.4" in str(excinfo.value)


# --- The normal path must keep working -------------------------------


async def test_remote_send_command_still_uses_own_hardware(
    hass: HomeAssistant, mock_config_entry_data: dict
) -> None:
    """Being pluckable is additive: remote.send_command is unchanged.

    It goes out through the ESPHome service, not the infrared platform.
    """
    await _setup_with_remote(hass, mock_config_entry_data, [("TV Power", 38000)])

    with patch(
        "custom_components.openirblaster.button.async_send_code_via_esphome",
        new=AsyncMock(),
    ) as sender:
        await hass.services.async_call(
            "remote",
            "send_command",
            {
                "entity_id": _remote_entity_id(hass),
                "command": ["TV Power"],
            },
            blocking=True,
        )

    assert sender.await_count == 1
    assert sender.await_args.args[2] == 38000
    assert sender.await_args.args[3] == PULSES
