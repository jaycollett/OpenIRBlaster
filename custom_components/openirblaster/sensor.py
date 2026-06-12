"""Sensor platform for OpenIRBlaster."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import RestoreSensor, SensorDeviceClass
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_DEVICE_ID,
    CONF_MAC_ADDRESS,
    DOMAIN,
    SIGNAL_CODE_ADDED,
    STATE_RECEIVED,
    UNIQUE_ID_LAST_LEARNED_AT,
    UNIQUE_ID_LAST_LEARNED_LEN,
    UNIQUE_ID_LAST_LEARNED_NAME,
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
    """Set up OpenIRBlaster sensor entities."""
    learning_session = entry.runtime_data.learning_session

    entities: list[RestoreSensor] = [
        LastLearnedNameSensor(entry, learning_session),
        LastLearnedTimestampSensor(entry, learning_session),
        LastLearnedLengthSensor(entry, learning_session),
    ]

    async_add_entities(entities)


class OpenIRBlasterSensorBase(RestoreSensor):
    """Base class for OpenIRBlaster sensors."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        entry: OpenIRBlasterConfigEntry,
        learning_session: LearningSession,
    ) -> None:
        """Initialize the sensor."""
        self._entry = entry
        self._learning_session = learning_session
        self._last_learned_code: LearnedCode | None = None
        self._restored_native_value = None

        device_id = entry.data[CONF_DEVICE_ID]
        mac_address = entry.data.get(CONF_MAC_ADDRESS)

        # Use MAC-based identifier if available (matches device registration in __init__.py)
        if mac_address:
            normalized_mac = mac_address.lower().replace(":", "")
            device_identifier = normalized_mac
        else:
            device_identifier = device_id

        # Device already created in __init__.py, just reference it
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_identifier)},
        )

    async def async_added_to_hass(self) -> None:
        """Restore last state and subscribe to learning-session changes."""
        await super().async_added_to_hass()
        last = await self.async_get_last_sensor_data()
        if last is not None:
            self._restored_native_value = last.native_value
        # Registered here (not in __init__) so the callback only fires while
        # the entity is added to hass; unregistered in
        # async_will_remove_from_hass since register_callback returns no
        # unsubscribe callable.
        self._learning_session.register_callback(self._handle_state_change)
        # A code save updates the storage-backed last-learned metadata.
        # Saves no longer reload the entry, so refresh on the save signal.
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_CODE_ADDED.format(entry_id=self._entry.entry_id),
                self._async_handle_code_added,
            )
        )

    async def async_will_remove_from_hass(self) -> None:
        """Clean up when entity is removed."""
        self._learning_session.unregister_callback(self._handle_state_change)
        await super().async_will_remove_from_hass()

    def _handle_state_change(self, state: str, code: LearnedCode | None) -> None:
        """Handle learning session state change."""
        if state == STATE_RECEIVED and code is not None:
            # Store the last learned code so it persists after pending is cleared
            self._last_learned_code = code
            self.async_schedule_update_ha_state(True)

    @callback
    def _async_handle_code_added(self, code: dict[str, Any]) -> None:
        """Refresh after a save updated the last-learned metadata."""
        self.async_schedule_update_ha_state(True)

    def _storage_last_learned(self) -> dict[str, Any] | None:
        """Get storage-backed last-learned metadata, if available."""
        data = getattr(self._entry, "runtime_data", None)
        if data is None:
            return None
        return data.storage.get_last_learned()


class LastLearnedNameSensor(OpenIRBlasterSensorBase):
    """Sensor showing the name/ID of the last learned code."""

    _attr_translation_key = "last_learned_name"

    def __init__(
        self,
        entry: OpenIRBlasterConfigEntry,
        learning_session: LearningSession,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(entry, learning_session)
        self._attr_unique_id = UNIQUE_ID_LAST_LEARNED_NAME.format(
            entry_id=entry.entry_id
        )

    @property
    def native_value(self) -> str | None:
        """Return the state of the sensor."""
        # Storage-backed value survives reloads and restarts
        last = self._storage_last_learned()
        if last and last.get("name"):
            return last["name"]
        # Fallback to device_id if no name set yet
        if self._last_learned_code:
            return self._last_learned_code.device_id
        if self._restored_native_value:
            return str(self._restored_native_value)
        return None


class LastLearnedTimestampSensor(OpenIRBlasterSensorBase):
    """Sensor showing when the last code was learned."""

    _attr_translation_key = "last_learned_timestamp"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(
        self,
        entry: OpenIRBlasterConfigEntry,
        learning_session: LearningSession,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(entry, learning_session)
        self._attr_unique_id = UNIQUE_ID_LAST_LEARNED_AT.format(
            entry_id=entry.entry_id
        )

    @property
    def native_value(self) -> datetime | None:
        """Return the state of the sensor."""
        # Storage-backed value survives reloads and restarts
        last = self._storage_last_learned()
        if last and last.get("timestamp"):
            try:
                return datetime.fromisoformat(
                    last["timestamp"].replace("Z", "+00:00")
                )
            except ValueError:
                _LOGGER.warning("Could not parse timestamp: %s", last["timestamp"])
        # Fallback to in-memory code
        if self._last_learned_code and self._last_learned_code.timestamp:
            try:
                return datetime.fromisoformat(self._last_learned_code.timestamp.replace("Z", "+00:00"))
            except ValueError:
                _LOGGER.warning("Could not parse timestamp: %s", self._last_learned_code.timestamp)
        if self._restored_native_value:
            if isinstance(self._restored_native_value, datetime):
                return self._restored_native_value
            try:
                return datetime.fromisoformat(str(self._restored_native_value).replace("Z", "+00:00"))
            except ValueError:
                _LOGGER.warning("Could not parse restored timestamp: %s", self._restored_native_value)
        return None


class LastLearnedLengthSensor(OpenIRBlasterSensorBase):
    """Sensor showing the pulse count of the last learned code."""

    _attr_translation_key = "last_learned_pulse_count"
    _attr_native_unit_of_measurement = "pulses"

    def __init__(
        self,
        entry: OpenIRBlasterConfigEntry,
        learning_session: LearningSession,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(entry, learning_session)
        self._attr_unique_id = UNIQUE_ID_LAST_LEARNED_LEN.format(
            entry_id=entry.entry_id
        )

    @property
    def native_value(self) -> int | None:
        """Return the state of the sensor."""
        # Storage-backed value survives reloads and restarts
        last = self._storage_last_learned()
        if last and last.get("pulse_count") is not None:
            return last["pulse_count"]
        # Fallback to in-memory code
        if self._last_learned_code:
            return len(self._last_learned_code.pulses)
        if self._restored_native_value is not None:
            try:
                return int(self._restored_native_value)
            except (TypeError, ValueError):
                _LOGGER.warning("Could not parse restored pulse count: %s", self._restored_native_value)
        return None
