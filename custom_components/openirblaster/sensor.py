"""Sensor platform for OpenIRBlaster."""

from __future__ import annotations

import logging
from datetime import datetime

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_DEVICE_ID,
    DOMAIN,
    STATE_RECEIVED,
    UNIQUE_ID_LAST_LEARNED_AT,
    UNIQUE_ID_LAST_LEARNED_LEN,
    UNIQUE_ID_LAST_LEARNED_NAME,
)
from .learning import LearnedCode, LearningSession

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up OpenIRBlaster sensor entities."""
    learning_session: LearningSession = hass.data[DOMAIN][entry.entry_id][
        "learning_session"
    ]

    entities: list[SensorEntity] = [
        LastLearnedNameSensor(entry, learning_session),
        LastLearnedTimestampSensor(entry, learning_session),
        LastLearnedLengthSensor(entry, learning_session),
    ]

    async_add_entities(entities)


class OpenIRBlasterSensorBase(SensorEntity):
    """Base class for OpenIRBlaster sensors."""

    _attr_has_entity_name = True

    def __init__(
        self,
        entry: ConfigEntry,
        learning_session: LearningSession,
    ) -> None:
        """Initialize the sensor."""
        self._entry = entry
        self._learning_session = learning_session
        self._last_learned_code: LearnedCode | None = None

        device_id = entry.data[CONF_DEVICE_ID]
        # Device already created in __init__.py, just reference it
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
        )

        # Register callback for learning session state changes
        learning_session.register_callback(self._handle_state_change)

    async def async_will_remove_from_hass(self) -> None:
        """Clean up when entity is removed."""
        # Unregister callback to prevent callback leak
        self._learning_session.unregister_callback(self._handle_state_change)

    def _handle_state_change(self, state: str, code: LearnedCode | None) -> None:
        """Handle learning session state change."""
        if state == STATE_RECEIVED and code is not None:
            # Store the last learned code so it persists after pending is cleared
            self._last_learned_code = code
            # Schedule update safely - check if entity is still added to hass
            if self.hass is not None and self.entity_id is not None:
                self.async_schedule_update_ha_state(True)


class LastLearnedNameSensor(OpenIRBlasterSensorBase):
    """Sensor showing the name/ID of the last learned code."""

    def __init__(
        self,
        entry: ConfigEntry,
        learning_session: LearningSession,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(entry, learning_session)
        self._attr_unique_id = UNIQUE_ID_LAST_LEARNED_NAME.format(
            entry_id=entry.entry_id
        )
        self._attr_name = "Last Learned Code Name"
        self._attr_icon = "mdi:tag"

    @property
    def native_value(self) -> str | None:
        """Return the state of the sensor."""
        # Read the last learned name from hass.data
        if self.hass and self._entry.entry_id in self.hass.data.get(DOMAIN, {}):
            last_name = self.hass.data[DOMAIN][self._entry.entry_id].get("last_learned_name")
            if last_name:
                return last_name
        # Fallback to device_id if no name set yet
        if self._last_learned_code:
            return self._last_learned_code.device_id
        return None


class LastLearnedTimestampSensor(OpenIRBlasterSensorBase):
    """Sensor showing when the last code was learned."""

    def __init__(
        self,
        entry: ConfigEntry,
        learning_session: LearningSession,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(entry, learning_session)
        self._attr_unique_id = UNIQUE_ID_LAST_LEARNED_AT.format(
            entry_id=entry.entry_id
        )
        self._attr_name = "Last Learned Timestamp"
        self._attr_icon = "mdi:clock"
        self._attr_device_class = SensorDeviceClass.TIMESTAMP

    @property
    def native_value(self) -> datetime | None:
        """Return the state of the sensor."""
        if self._last_learned_code and self._last_learned_code.timestamp:
            try:
                # Parse ISO timestamp
                return datetime.fromisoformat(self._last_learned_code.timestamp.replace("Z", "+00:00"))
            except ValueError:
                _LOGGER.warning("Could not parse timestamp: %s", self._last_learned_code.timestamp)
        return None


class LastLearnedLengthSensor(OpenIRBlasterSensorBase):
    """Sensor showing the pulse count of the last learned code."""

    def __init__(
        self,
        entry: ConfigEntry,
        learning_session: LearningSession,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(entry, learning_session)
        self._attr_unique_id = UNIQUE_ID_LAST_LEARNED_LEN.format(
            entry_id=entry.entry_id
        )
        self._attr_name = "Last Learned Pulse Count"
        self._attr_icon = "mdi:counter"
        self._attr_native_unit_of_measurement = "pulses"

    @property
    def native_value(self) -> int | None:
        """Return the state of the sensor."""
        if self._last_learned_code:
            return len(self._last_learned_code.pulses)
        return None
