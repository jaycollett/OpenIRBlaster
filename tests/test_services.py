"""Tests for services module."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er

from custom_components.openirblaster.const import (
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
from custom_components.openirblaster.learning import LearnedCode
from custom_components.openirblaster.services import async_setup_services


async def test_setup_services(hass: HomeAssistant) -> None:
    """Test that services are registered."""
    await async_setup_services(hass)

    # Verify services are registered
    assert hass.services.has_service(DOMAIN, SERVICE_LEARN_START)
    assert hass.services.has_service(DOMAIN, SERVICE_SEND_CODE)
    assert hass.services.has_service(DOMAIN, SERVICE_DELETE_CODE)
    assert hass.services.has_service(DOMAIN, SERVICE_RENAME_CODE)
    assert hass.services.has_service(DOMAIN, SERVICE_SAVE_PENDING)


async def test_service_rejects_unknown_entry(hass: HomeAssistant) -> None:
    """A config_entry_id that does not exist raises config_entry_not_found."""
    await async_setup_services(hass)

    with pytest.raises(ServiceValidationError) as excinfo:
        await hass.services.async_call(
            DOMAIN,
            SERVICE_LEARN_START,
            {"config_entry_id": "does_not_exist"},
            blocking=True,
        )

    assert excinfo.value.translation_key == "config_entry_not_found"


async def test_service_rejects_not_loaded_entry(
    hass: HomeAssistant, mock_config_entry_data: dict
) -> None:
    """An entry that exists but is not loaded raises config_entry_not_loaded.

    Services are registered in async_setup, so they exist even when no
    entry is loaded; the handlers must verify the entry state themselves.
    """
    await async_setup_services(hass)

    entry = MockConfigEntry(domain=DOMAIN, data=mock_config_entry_data)
    entry.add_to_hass(hass)  # added, never set up -> NOT_LOADED

    with pytest.raises(ServiceValidationError) as excinfo:
        await hass.services.async_call(
            DOMAIN,
            SERVICE_LEARN_START,
            {"config_entry_id": entry.entry_id},
            blocking=True,
        )

    assert excinfo.value.translation_key == "config_entry_not_loaded"


async def test_learn_start_service(
    hass: HomeAssistant, mock_config_entry_data: dict
) -> None:
    """Test learn_start service."""
    entry = MockConfigEntry(domain=DOMAIN, data=mock_config_entry_data)
    entry.add_to_hass(hass)

    with patch(
        "homeassistant.config_entries.ConfigEntries.async_forward_entry_setups",
        return_value=True,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    learning_session = entry.runtime_data.learning_session

    with patch.object(
        learning_session, "async_start_learning", return_value=True
    ) as mock_start:
        await hass.services.async_call(
            DOMAIN,
            SERVICE_LEARN_START,
            {"config_entry_id": entry.entry_id, "timeout": 10},
            blocking=True,
        )

        # The override is passed per-call; the session default is untouched
        mock_start.assert_awaited_once_with(timeout=10)
        assert learning_session.timeout == 30


async def test_learn_start_timeout_override_is_per_session(
    hass: HomeAssistant, mock_config_entry_data: dict
) -> None:
    """A learn_start timeout override must not stick for later sessions.

    The handler used to assign ``learning_session.timeout = timeout``,
    permanently mutating the default. After a learn_start with timeout 120,
    a subsequent button-initiated session (no override) must schedule the
    default 30 seconds again.
    """
    import custom_components.openirblaster.learning as learning_module

    entry = MockConfigEntry(domain=DOMAIN, data=mock_config_entry_data)
    entry.add_to_hass(hass)

    with patch(
        "homeassistant.config_entries.ConfigEntries.async_forward_entry_setups",
        return_value=True,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    learning_session = entry.runtime_data.learning_session

    hass.services.async_register("switch", "turn_on", AsyncMock())
    hass.services.async_register("switch", "turn_off", AsyncMock())

    delays: list[float] = []
    real_async_call_later = learning_module.async_call_later

    def spy_async_call_later(hass_, delay, action):
        delays.append(delay)
        return real_async_call_later(hass_, delay, action)

    with patch.object(
        learning_module, "async_call_later", side_effect=spy_async_call_later
    ):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_LEARN_START,
            {"config_entry_id": entry.entry_id, "timeout": 120},
            blocking=True,
        )
        assert delays == [120]
        assert learning_session.timeout == 30  # default not mutated

        await learning_session.async_clear_pending()

        # A subsequent session without an override uses the default again
        assert await learning_session.async_start_learning() is True
        assert delays == [120, 30]

    await learning_session.async_cleanup()


async def test_send_code_service(
    hass: HomeAssistant, mock_config_entry_data: dict, mock_stored_code: dict
) -> None:
    """Test send_code service."""
    # Register ESPHome service BEFORE integration setup (so discovery finds it)
    esphome_calls = []

    async def mock_esphome_service(call):
        esphome_calls.append(call)

    hass.services.async_register(
        "esphome", "openirblaster_test_send_ir_raw", mock_esphome_service
    )

    entry = MockConfigEntry(domain=DOMAIN, data=mock_config_entry_data)
    entry.add_to_hass(hass)

    with patch(
        "homeassistant.config_entries.ConfigEntries.async_forward_entry_setups",
        return_value=True,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    # Add a code to storage
    storage = entry.runtime_data.storage
    await storage.async_add_code(
        name="Test Code",
        carrier_hz=38000,
        pulses=[9000, -4500],
    )

    await hass.services.async_call(
        DOMAIN,
        SERVICE_SEND_CODE,
        {
            "config_entry_id": entry.entry_id,
            ATTR_CODE_ID: "test_code",
        },
        blocking=True,
    )

    # Verify ESPHome service was called
    assert len(esphome_calls) == 1
    assert esphome_calls[0].data["carrier_hz"] == 38000
    assert esphome_calls[0].data["code"] == [9000, -4500]


async def test_delete_code_service(
    hass: HomeAssistant, mock_config_entry_data: dict
) -> None:
    """Test delete_code service."""
    entry = MockConfigEntry(domain=DOMAIN, data=mock_config_entry_data)
    entry.add_to_hass(hass)

    with patch(
        "homeassistant.config_entries.ConfigEntries.async_forward_entry_setups",
        return_value=True,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    # Add a code to storage
    storage = entry.runtime_data.storage
    await storage.async_add_code(
        name="Test Code",
        carrier_hz=38000,
        pulses=[9000, -4500],
    )

    assert len(storage.get_codes()) == 1

    with patch("homeassistant.config_entries.ConfigEntries.async_reload"):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_DELETE_CODE,
            {
                "config_entry_id": entry.entry_id,
                ATTR_CODE_ID: "test_code",
            },
            blocking=True,
        )

    # Verify code was deleted
    assert len(storage.get_codes()) == 0


async def test_rename_code_service(
    hass: HomeAssistant, mock_config_entry_data: dict
) -> None:
    """Test rename_code service."""
    entry = MockConfigEntry(domain=DOMAIN, data=mock_config_entry_data)
    entry.add_to_hass(hass)

    with patch(
        "homeassistant.config_entries.ConfigEntries.async_forward_entry_setups",
        return_value=True,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    # Add a code to storage
    storage = entry.runtime_data.storage
    await storage.async_add_code(
        name="Old Name",
        carrier_hz=38000,
        pulses=[9000, -4500],
    )

    with patch("homeassistant.config_entries.ConfigEntries.async_reload"):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_RENAME_CODE,
            {
                "config_entry_id": entry.entry_id,
                ATTR_CODE_ID: "old_name",
                "new_name": "New Name",
            },
            blocking=True,
        )

    # Verify code was renamed
    code = storage.get_code("old_name")
    assert code is not None
    assert code["name"] == "New Name"


async def test_delete_code_service_removes_registry_entry(
    hass: HomeAssistant, mock_config_entry_data: dict
) -> None:
    """Service-based delete must clean the code button out of the registry.

    The options-flow delete path already removed registry entries; the
    service path used to skip it, leaving an orphaned "no longer provided"
    button entity behind after the reload.
    """
    entry = MockConfigEntry(domain=DOMAIN, data=mock_config_entry_data)
    entry.add_to_hass(hass)

    with patch(
        "homeassistant.config_entries.ConfigEntries.async_forward_entry_setups",
        return_value=True,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    storage = entry.runtime_data.storage
    await storage.async_add_code(
        name="Test Code",
        carrier_hz=38000,
        pulses=[9000, -4500],
    )

    # Register the code's button entity as the button platform would
    registry = er.async_get(hass)
    unique_id = f"{entry.entry_id}_test_code"
    registry.async_get_or_create(
        domain="button",
        platform=DOMAIN,
        unique_id=unique_id,
        config_entry=entry,
    )
    assert registry.async_get_entity_id("button", DOMAIN, unique_id) is not None

    with patch("homeassistant.config_entries.ConfigEntries.async_reload"):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_DELETE_CODE,
            {
                "config_entry_id": entry.entry_id,
                ATTR_CODE_ID: "test_code",
            },
            blocking=True,
        )

    assert len(storage.get_codes()) == 0
    # The registry entry is gone, not orphaned
    assert registry.async_get_entity_id("button", DOMAIN, unique_id) is None


async def test_save_pending_rejects_duplicate_name(
    hass: HomeAssistant, mock_config_entry_data: dict
) -> None:
    """save_pending must reject a name that already exists in storage."""
    entry = MockConfigEntry(domain=DOMAIN, data=mock_config_entry_data)
    entry.add_to_hass(hass)

    with patch(
        "homeassistant.config_entries.ConfigEntries.async_forward_entry_setups",
        return_value=True,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    storage = entry.runtime_data.storage
    await storage.async_add_code(
        name="TV Power",
        carrier_hz=38000,
        pulses=[9000, -4500],
    )

    learning_session = entry.runtime_data.learning_session
    learning_session._pending_code = LearnedCode(
        carrier_hz=38000,
        pulses=[9000, -4500, 560, -560],
        timestamp="2026-01-12T14:30:00-05:00",
        device_id="openirblaster-test123",
    )

    with pytest.raises(ServiceValidationError) as excinfo:
        await hass.services.async_call(
            DOMAIN,
            SERVICE_SAVE_PENDING,
            {
                "config_entry_id": entry.entry_id,
                "name": "TV Power",
            },
            blocking=True,
        )

    assert excinfo.value.translation_key == "name_exists"
    # The pending code is untouched and nothing new was stored
    assert learning_session.pending_code is not None
    assert len(storage.get_codes()) == 1
