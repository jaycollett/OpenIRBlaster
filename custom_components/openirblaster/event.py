"""Event platform for OpenIRBlaster."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.event import EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    ATTR_CARRIER_HZ,
    ATTR_CODE_ID,
    ATTR_CODE_NAME,
    ATTR_PULSES,
    CONF_DEVICE_ID,
    CONF_MAC_ADDRESS,
    DOMAIN,
    EVENT_TYPE_CODE_LEARNED,
    EVENT_TYPE_CODE_SAVED,
    SIGNAL_CODE_ADDED,
    STATE_RECEIVED,
    UNIQUE_ID_CODE_ACTIVITY_EVENT,
)
from .data import OpenIRBlasterConfigEntry
from .learning import LearnedCode, LearningSession

_LOGGER = logging.getLogger(__name__)

# Push-based integration: no parallel polling coordination needed
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: OpenIRBlasterConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the OpenIRBlaster event entity."""
    async_add_entities(
        [CodeActivityEvent(entry, entry.runtime_data.learning_session)]
    )


class CodeActivityEvent(EventEntity):
    """Event entity for IR code activity (captures and saves).

    Deliberately uncategorized: users automate on these events, so they
    belong with the primary controls rather than under DIAGNOSTIC.
    """

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "code_activity"
    _attr_event_types = [EVENT_TYPE_CODE_LEARNED, EVENT_TYPE_CODE_SAVED]

    def __init__(
        self,
        entry: OpenIRBlasterConfigEntry,
        learning_session: LearningSession,
    ) -> None:
        """Initialize the event entity."""
        self._entry = entry
        self._learning_session = learning_session
        self._attr_unique_id = UNIQUE_ID_CODE_ACTIVITY_EVENT.format(
            entry_id=entry.entry_id
        )

        device_id = entry.data[CONF_DEVICE_ID]
        mac_address = entry.data.get(CONF_MAC_ADDRESS)

        # Use MAC-based identifier if available (matches device registration in __init__.py)
        if mac_address:
            base_identifier = mac_address.lower().replace(":", "")
        else:
            base_identifier = device_id

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, base_identifier)},
        )

    async def async_added_to_hass(self) -> None:
        """Subscribe to capture and save notifications."""
        await super().async_added_to_hass()
        # Captures arrive via the learning-session callback (no unsubscribe
        # callable returned, so the symmetric unregister lives in
        # async_will_remove_from_hass, mirroring the sensors).
        self._learning_session.register_callback(self._handle_state_change)
        # Saves arrive via the existing dispatcher signal carrying the
        # stored code dict.
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_CODE_ADDED.format(entry_id=self._entry.entry_id),
                self._async_handle_code_saved,
            )
        )

    async def async_will_remove_from_hass(self) -> None:
        """Unsubscribe from the learning session."""
        self._learning_session.unregister_callback(self._handle_state_change)
        await super().async_will_remove_from_hass()

    def _handle_state_change(self, state: str, code: LearnedCode | None) -> None:
        """Fire code_learned when a capture is finalized."""
        if state != STATE_RECEIVED or code is None:
            return
        attributes: dict[str, Any] = {
            "carrier_hz": code.carrier_hz,
            "pulse_count": len(code.pulses),
            "timestamp": code.timestamp,
        }
        if code.rssi is not None:
            attributes["rssi"] = code.rssi
        self._trigger_event(EVENT_TYPE_CODE_LEARNED, attributes)
        self.async_write_ha_state()

    @callback
    def _async_handle_code_saved(self, code: dict[str, Any]) -> None:
        """Fire code_saved when a code is stored."""
        self._trigger_event(
            EVENT_TYPE_CODE_SAVED,
            {
                "code_id": code.get(ATTR_CODE_ID),
                "name": code.get(ATTR_CODE_NAME),
                "carrier_hz": code.get(ATTR_CARRIER_HZ),
                "pulse_count": len(code.get(ATTR_PULSES) or []),
            },
        )
        self.async_write_ha_state()
