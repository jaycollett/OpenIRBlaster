"""Tests for dispatcher-based dynamic entities and the single-device layout.

These tests run the real button/sensor/text platforms (no patched
forward_entry_setups) so they can observe live entities appearing,
renaming, and disappearing without entry reloads.
"""

from __future__ import annotations

from unittest.mock import patch

from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import (
    device_registry as dr,
    entity_platform as ep,
    entity_registry as er,
)

from custom_components.openirblaster.button import LearnButton
from custom_components.openirblaster.const import (
    ATTR_CODE_ID,
    DOMAIN,
    SERVICE_DELETE_CODE,
    SERVICE_RENAME_CODE,
    SERVICE_SAVE_PENDING,
    STATE_IDLE,
    STATE_RECEIVED,
    UNIQUE_ID_CODE_NAME_INPUT,
    UNIQUE_ID_LEARN_BUTTON,
)
from custom_components.openirblaster.learning import LearnedCode


async def _async_setup_real_entry(
    hass: HomeAssistant, data: dict
) -> MockConfigEntry:
    """Set up an entry with real platforms (button, sensor, text)."""
    entry = MockConfigEntry(domain=DOMAIN, data=data)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _set_pending_code(entry: MockConfigEntry) -> None:
    """Put a pending learned code on the entry's session."""
    session = entry.runtime_data.learning_session
    session._state = STATE_RECEIVED
    session._pending_code = LearnedCode(
        carrier_hz=38000,
        pulses=[9000, -4500, 560, -560],
        timestamp="2026-01-12T14:30:00-05:00",
        device_id="openirblaster-test123",
    )


def _code_button_entity_id(
    hass: HomeAssistant, entry: MockConfigEntry, code_id: str
) -> str | None:
    registry = er.async_get(hass)
    return registry.async_get_entity_id(
        "button", DOMAIN, f"{entry.entry_id}_{code_id}"
    )


async def test_save_pending_service_adds_button_without_reload(
    hass: HomeAssistant, mock_config_entry_data: dict
) -> None:
    """save_pending creates a live button via dispatcher, with no reload."""
    entry = await _async_setup_real_entry(hass, mock_config_entry_data)
    session = entry.runtime_data.learning_session
    _set_pending_code(entry)

    with patch(
        "homeassistant.config_entries.ConfigEntries.async_reload"
    ) as mock_reload:
        await hass.services.async_call(
            DOMAIN,
            SERVICE_SAVE_PENDING,
            {"config_entry_id": entry.entry_id, "name": "TV Power"},
            blocking=True,
        )
        await hass.async_block_till_done()

    mock_reload.assert_not_called()

    # The button exists as a live entity
    entity_id = _code_button_entity_id(hass, entry, "tv_power")
    assert entity_id is not None
    assert hass.states.get(entity_id) is not None

    # The learning session survived the save: same object, reset to IDLE
    assert entry.runtime_data.learning_session is session
    assert session.state == STATE_IDLE
    assert session.pending_code is None

    # The last-learned sensors refreshed from storage without a reload
    registry = er.async_get(hass)
    name_sensor_id = registry.async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_last_learned_name"
    )
    assert name_sensor_id is not None
    assert hass.states.get(name_sensor_id).state == "TV Power"
    count_sensor_id = registry.async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_last_learned_len"
    )
    assert hass.states.get(count_sensor_id).state == "4"


async def test_options_flow_save_adds_button_without_reload(
    hass: HomeAssistant, mock_config_entry_data: dict
) -> None:
    """The options-flow save path adds the button dynamically, no reload."""
    from homeassistant.data_entry_flow import FlowResultType

    entry = await _async_setup_real_entry(hass, mock_config_entry_data)
    _set_pending_code(entry)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["step_id"] == "save_code"

    with patch(
        "homeassistant.config_entries.ConfigEntries.async_reload"
    ) as mock_reload:
        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            user_input={"name": "Ceiling Fan"},
        )
        await hass.async_block_till_done()

    assert result["type"] == FlowResultType.CREATE_ENTRY
    mock_reload.assert_not_called()

    entity_id = _code_button_entity_id(hass, entry, "ceiling_fan")
    assert entity_id is not None
    assert hass.states.get(entity_id) is not None


async def test_learn_button_save_path_adds_button_without_reload(
    hass: HomeAssistant, mock_config_entry_data: dict
) -> None:
    """The LearnButton save path adds the button dynamically, no reload.

    Also verifies the explicit side effects formerly piggybacking on the
    reload: the code-name text entity is cleared and the session is reset.
    """
    entry = await _async_setup_real_entry(hass, mock_config_entry_data)
    session = entry.runtime_data.learning_session
    _set_pending_code(entry)

    # Find the live LearnButton entity object on the platform
    learn_button: LearnButton | None = None
    for platform in ep.async_get_platforms(hass, DOMAIN):
        for entity in platform.entities.values():
            if isinstance(entity, LearnButton):
                learn_button = entity
    assert learn_button is not None

    # Give the text entity a value, as if the user typed a name
    registry = er.async_get(hass)
    text_entity_id = registry.async_get_entity_id(
        "text", DOMAIN, UNIQUE_ID_CODE_NAME_INPUT.format(entry_id=entry.entry_id)
    )
    await hass.services.async_call(
        "text",
        "set_value",
        {"entity_id": text_entity_id, "value": "Sound Bar"},
        blocking=True,
    )

    learn_button._pending_save_name = "Sound Bar"

    with patch(
        "homeassistant.config_entries.ConfigEntries.async_reload"
    ) as mock_reload:
        await learn_button._async_save_learned_code()
        await hass.async_block_till_done()

    mock_reload.assert_not_called()

    # New button is live
    entity_id = _code_button_entity_id(hass, entry, "sound_bar")
    assert entity_id is not None
    assert hass.states.get(entity_id) is not None

    # Former reload side effects now happen explicitly:
    # the text input was cleared and the session was reset
    assert hass.states.get(text_entity_id).state == ""
    assert entry.runtime_data.learning_session is session
    assert session.state == STATE_IDLE
    assert session.pending_code is None


async def test_delete_code_service_removes_live_entity(
    hass: HomeAssistant, mock_config_entry_data: dict
) -> None:
    """Deleting a code removes the live entity without a reload."""
    entry = await _async_setup_real_entry(hass, mock_config_entry_data)
    _set_pending_code(entry)

    await hass.services.async_call(
        DOMAIN,
        SERVICE_SAVE_PENDING,
        {"config_entry_id": entry.entry_id, "name": "TV Power"},
        blocking=True,
    )
    await hass.async_block_till_done()

    entity_id = _code_button_entity_id(hass, entry, "tv_power")
    assert hass.states.get(entity_id) is not None

    with patch(
        "homeassistant.config_entries.ConfigEntries.async_reload"
    ) as mock_reload:
        await hass.services.async_call(
            DOMAIN,
            SERVICE_DELETE_CODE,
            {"config_entry_id": entry.entry_id, ATTR_CODE_ID: "tv_power"},
            blocking=True,
        )
        await hass.async_block_till_done()

    mock_reload.assert_not_called()

    # Registry entry gone and the live entity removed with it
    assert _code_button_entity_id(hass, entry, "tv_power") is None
    assert hass.states.get(entity_id) is None


async def test_rename_code_service_updates_live_entity_name(
    hass: HomeAssistant, mock_config_entry_data: dict
) -> None:
    """Renaming a code updates the live entity's name without a reload."""
    entry = await _async_setup_real_entry(hass, mock_config_entry_data)
    _set_pending_code(entry)

    await hass.services.async_call(
        DOMAIN,
        SERVICE_SAVE_PENDING,
        {"config_entry_id": entry.entry_id, "name": "TV Power"},
        blocking=True,
    )
    await hass.async_block_till_done()

    entity_id = _code_button_entity_id(hass, entry, "tv_power")
    assert "TV Power" in hass.states.get(entity_id).attributes["friendly_name"]

    with patch(
        "homeassistant.config_entries.ConfigEntries.async_reload"
    ) as mock_reload:
        await hass.services.async_call(
            DOMAIN,
            SERVICE_RENAME_CODE,
            {
                "config_entry_id": entry.entry_id,
                ATTR_CODE_ID: "tv_power",
                "new_name": "Samsung TV Power",
            },
            blocking=True,
        )
        await hass.async_block_till_done()

    mock_reload.assert_not_called()

    # Same entity (code_id is stable), new friendly name
    state = hass.states.get(entity_id)
    assert state is not None
    assert "Samsung TV Power" in state.attributes["friendly_name"]


async def test_fresh_setup_single_device_with_categories(
    hass: HomeAssistant, mock_config_entry_data: dict
) -> None:
    """A fresh setup creates one device with correctly categorized entities."""
    entry = await _async_setup_real_entry(hass, mock_config_entry_data)

    device_registry = dr.async_get(hass)
    devices = dr.async_entries_for_config_entry(device_registry, entry.entry_id)
    assert len(devices) == 1
    main_device = devices[0]

    registry = er.async_get(hass)
    expected = {
        ("button", f"{entry.entry_id}_learn"): EntityCategory.CONFIG,
        ("button", f"{entry.entry_id}_send_last"): EntityCategory.CONFIG,
        ("text", f"{entry.entry_id}_code_name_input"): EntityCategory.CONFIG,
        ("sensor", f"{entry.entry_id}_last_learned_name"): EntityCategory.DIAGNOSTIC,
        ("sensor", f"{entry.entry_id}_last_learned_at"): EntityCategory.DIAGNOSTIC,
        ("sensor", f"{entry.entry_id}_last_learned_len"): EntityCategory.DIAGNOSTIC,
    }
    for (domain, unique_id), category in expected.items():
        entity_id = registry.async_get_entity_id(domain, DOMAIN, unique_id)
        assert entity_id is not None, f"missing {domain}/{unique_id}"
        entity = registry.async_get(entity_id)
        assert entity.entity_category == category, entity_id
        assert entity.device_id == main_device.id, entity_id

    # CodeButtons (primary controls) stay uncategorized on the main device
    _set_pending_code(entry)
    await hass.services.async_call(
        DOMAIN,
        SERVICE_SAVE_PENDING,
        {"config_entry_id": entry.entry_id, "name": "TV Power"},
        blocking=True,
    )
    await hass.async_block_till_done()

    code_entity_id = _code_button_entity_id(hass, entry, "tv_power")
    code_entity = registry.async_get(code_entity_id)
    assert code_entity.entity_category is None
    assert code_entity.device_id == main_device.id


async def test_legacy_controls_device_is_migrated(
    hass: HomeAssistant, mock_config_entry_data: dict
) -> None:
    """Setup removes a leftover Controls device and re-points its entities."""
    entry = MockConfigEntry(domain=DOMAIN, data=mock_config_entry_data)
    entry.add_to_hass(hass)

    device_id = mock_config_entry_data["device_id"]
    device_registry = dr.async_get(hass)
    controls_device = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, f"{device_id}_controls")},
        name=f"OpenIRBlaster {device_id} Controls",
        manufacturer="OpenIRBlaster",
        model="Learning & Management",
    )

    # A legacy entity still attached to the Controls device
    registry = er.async_get(hass)
    legacy_entity = registry.async_get_or_create(
        domain="button",
        platform=DOMAIN,
        unique_id=UNIQUE_ID_LEARN_BUTTON.format(entry_id=entry.entry_id),
        config_entry=entry,
        device_id=controls_device.id,
    )
    assert legacy_entity.device_id == controls_device.id

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    # The Controls device is gone; only the main device remains
    assert (
        device_registry.async_get_device(
            identifiers={(DOMAIN, f"{device_id}_controls")}
        )
        is None
    )
    devices = dr.async_entries_for_config_entry(device_registry, entry.entry_id)
    assert len(devices) == 1
    main_device = devices[0]
    assert (DOMAIN, device_id) in main_device.identifiers

    # The legacy entity was re-pointed to the main device (and kept its
    # registry entry, so user customizations survive)
    migrated = registry.async_get(legacy_entity.entity_id)
    assert migrated is not None
    assert migrated.device_id == main_device.id

    # Idempotent: a reload (which re-runs setup) is a clean no-op
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert (
        device_registry.async_get_device(
            identifiers={(DOMAIN, f"{device_id}_controls")}
        )
        is None
    )
    assert len(
        dr.async_entries_for_config_entry(device_registry, entry.entry_id)
    ) == 1


async def test_stale_pending_name_does_not_hijack_later_capture(
    hass: HomeAssistant, mock_config_entry_data: dict
) -> None:
    """A timed-out press's name must not auto-save a later capture.

    QA probe: type a name, press Learn, let it time out, then arm via the
    learn_start service and capture. The capture must remain pending (for
    save_pending), not be silently saved under the stale old name.
    """
    import asyncio

    from unittest.mock import AsyncMock

    from homeassistant.core import Event

    from custom_components.openirblaster.const import (
        ATTR_CARRIER_HZ,
        ATTR_DEVICE_ID,
        ATTR_PULSES_JSON,
        ATTR_TIMESTAMP,
        EVENT_LEARNED,
        SERVICE_LEARN_START,
        STATE_ARMED,
        STATE_TIMEOUT,
    )

    entry = await _async_setup_real_entry(hass, mock_config_entry_data)
    session = entry.runtime_data.learning_session

    learn_button = None
    for platform in ep.async_get_platforms(hass, DOMAIN):
        for entity in platform.entities.values():
            if isinstance(entity, LearnButton):
                learn_button = entity
    assert learn_button is not None

    hass.services.async_register("switch", "turn_on", AsyncMock())
    hass.services.async_register("switch", "turn_off", AsyncMock())

    # Press with a typed name, then the session times out
    learn_button._pending_save_name = "Stale Name"
    session._state = STATE_TIMEOUT
    session._notify_state_change()
    await hass.async_block_till_done()

    # The stale name was dropped on TIMEOUT
    assert learn_button._pending_save_name is None

    # Later: arm via the service (terminal state resets automatically)
    await hass.services.async_call(
        DOMAIN,
        SERVICE_LEARN_START,
        {"config_entry_id": entry.entry_id},
        blocking=True,
    )
    assert session.state == STATE_ARMED

    session._async_handle_learned_event(
        Event(
            EVENT_LEARNED,
            {
                ATTR_DEVICE_ID: "openirblaster-test123",
                ATTR_CARRIER_HZ: 38000,
                ATTR_PULSES_JSON: "[9000,-4500,560,-560]",
                ATTR_TIMESTAMP: "2026-01-12T14:30:00-05:00",
            },
        )
    )
    await asyncio.sleep(0.1)
    await hass.async_block_till_done()

    # NOT auto-saved under the stale name; pending code still available
    assert entry.runtime_data.storage.get_codes() == []
    assert session.pending_code is not None
    assert session.state == STATE_RECEIVED


async def test_save_pending_service_clears_text_entity(
    hass: HomeAssistant, mock_config_entry_data: dict
) -> None:
    """A save via the save_pending service clears the Code Name input."""
    from custom_components.openirblaster.const import (
        SERVICE_SAVE_PENDING,
        UNIQUE_ID_CODE_NAME_INPUT,
    )

    entry = await _async_setup_real_entry(hass, mock_config_entry_data)
    _set_pending_code(entry)

    registry = er.async_get(hass)
    text_entity_id = registry.async_get_entity_id(
        "text", DOMAIN, UNIQUE_ID_CODE_NAME_INPUT.format(entry_id=entry.entry_id)
    )
    await hass.services.async_call(
        "text",
        "set_value",
        {"entity_id": text_entity_id, "value": "Half-typed name"},
        blocking=True,
    )
    assert hass.states.get(text_entity_id).state == "Half-typed name"

    await hass.services.async_call(
        DOMAIN,
        SERVICE_SAVE_PENDING,
        {"config_entry_id": entry.entry_id, "name": "TV Power"},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert hass.states.get(text_entity_id).state == ""


async def test_controls_migration_sweeps_pre_mac_identifier(
    hass: HomeAssistant, mock_config_entry_data: dict
) -> None:
    """The Controls sweep covers a pre-MAC install backfilled this boot.

    The legacy Controls device was created under the device_id identifier;
    the MAC back-fill on the same boot switches the main identifier to the
    MAC. The migration must sweep BOTH identifier forms.
    """
    from custom_components.openirblaster.const import UNIQUE_ID_LEARN_BUTTON

    assert "mac_address" not in mock_config_entry_data

    entry = MockConfigEntry(domain=DOMAIN, data=mock_config_entry_data)
    entry.add_to_hass(hass)

    device_id = mock_config_entry_data["device_id"]
    device_registry = dr.async_get(hass)

    # Legacy Controls device under the device_id identifier
    controls_device = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, f"{device_id}_controls")},
        name=f"OpenIRBlaster {device_id} Controls",
    )
    registry = er.async_get(hass)
    legacy_entity = registry.async_get_or_create(
        domain="button",
        platform=DOMAIN,
        unique_id=UNIQUE_ID_LEARN_BUTTON.format(entry_id=entry.entry_id),
        config_entry=entry,
        device_id=controls_device.id,
    )

    # ESPHome device with a MAC connection so the back-fill succeeds on
    # this same boot (main identifier becomes MAC-based)
    esphome_entry = MockConfigEntry(domain="esphome", data={})
    esphome_entry.add_to_hass(hass)
    device_registry.async_get_or_create(
        config_entry_id=esphome_entry.entry_id,
        connections={(dr.CONNECTION_NETWORK_MAC, "aa:bb:cc:dd:ee:ff")},
        identifiers={("esphome", "aabbccddeeff")},
        name=device_id,
    )

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    # MAC was back-filled, so the main device is MAC-keyed
    assert entry.data["mac_address"] == "aa:bb:cc:dd:ee:ff"
    main_device = device_registry.async_get_device(
        identifiers={(DOMAIN, "aabbccddeeff")}
    )
    assert main_device is not None

    # The device_id-keyed Controls device is gone, entity re-pointed
    assert (
        device_registry.async_get_device(
            identifiers={(DOMAIN, f"{device_id}_controls")}
        )
        is None
    )
    migrated = registry.async_get(legacy_entity.entity_id)
    assert migrated is not None
    assert migrated.device_id == main_device.id
