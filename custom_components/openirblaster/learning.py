"""Learning session management for OpenIRBlaster."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import event as ha_event

from .const import (
    ATTR_CARRIER_HZ,
    ATTR_DEVICE_ID,
    ATTR_PULSES,
    ATTR_PULSES_JSON,
    ATTR_TIMESTAMP,
    CONF_DEVICE_ID,
    CONF_LEARNING_SWITCH_ENTITY_ID,
    EVENT_LEARNED,
    LEARNING_TIMEOUT_SECONDS,
    MAX_PULSE_ARRAY_LENGTH,
    STATE_ARMED,
    STATE_CANCELLED,
    STATE_IDLE,
    STATE_RECEIVED,
    STATE_TIMEOUT,
)

_LOGGER = logging.getLogger(__name__)


@dataclass
class LearnedCode:
    """Represents a learned IR code."""

    carrier_hz: int
    pulses: list[int]
    timestamp: str
    device_id: str


class LearningSession:
    """Manage a learning session for an OpenIRBlaster device."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry_id: str,
        device_id: str,
        learning_switch_entity_id: str,
        timeout: int = LEARNING_TIMEOUT_SECONDS,
    ) -> None:
        """Initialize learning session."""
        self.hass = hass
        self.config_entry_id = config_entry_id
        self.device_id = device_id
        self.learning_switch_entity_id = learning_switch_entity_id
        self.timeout = timeout

        self._state = STATE_IDLE
        self._pending_code: LearnedCode | None = None
        self._event_listener: Callable | None = None
        self._timeout_handle: asyncio.TimerHandle | None = None
        self._callbacks: list[Callable[[str, LearnedCode | None], None]] = []

    @property
    def state(self) -> str:
        """Get current state."""
        return self._state

    @property
    def pending_code(self) -> LearnedCode | None:
        """Get pending learned code if available."""
        return self._pending_code

    def register_callback(
        self, callback_fn: Callable[[str, LearnedCode | None], None]
    ) -> None:
        """Register a callback for state changes."""
        self._callbacks.append(callback_fn)

    def unregister_callback(
        self, callback_fn: Callable[[str, LearnedCode | None], None]
    ) -> None:
        """Unregister a callback."""
        if callback_fn in self._callbacks:
            self._callbacks.remove(callback_fn)

    def _notify_state_change(self) -> None:
        """Notify all registered callbacks of state change."""
        # Iterate over a copy to allow callbacks to unregister during iteration
        # Catch exceptions to prevent one bad callback from crashing HA
        for callback_fn in self._callbacks[:]:
            try:
                callback_fn(self._state, self._pending_code)
            except Exception as err:
                _LOGGER.error("Error in learning session callback: %s", err, exc_info=True)

    async def async_start_learning(self) -> bool:
        """Start a learning session."""
        if self._state != STATE_IDLE:
            _LOGGER.warning(
                "Cannot start learning: session already in state %s", self._state
            )
            return False

        _LOGGER.info("Starting learning session for device %s", self.device_id)

        # Enable learning mode on the device
        try:
            await self.hass.services.async_call(
                "switch",
                "turn_on",
                {"entity_id": self.learning_switch_entity_id},
                blocking=True,
            )
        except Exception as err:
            _LOGGER.error("Failed to enable learning mode: %s", err)
            return False

        # Subscribe to learned events
        self._event_listener = self.hass.bus.async_listen(
            EVENT_LEARNED, self._async_handle_learned_event
        )

        # Set timeout
        self._timeout_handle = self.hass.loop.call_later(
            self.timeout, lambda: asyncio.create_task(self._async_handle_timeout())
        )

        self._state = STATE_ARMED
        self._notify_state_change()
        return True

    @callback
    def _async_handle_learned_event(self, event: Event) -> None:
        """Handle learned event from ESPHome device."""
        data = event.data

        # Filter by device_id
        event_device_id = data.get(ATTR_DEVICE_ID, "")
        if event_device_id != self.device_id:
            _LOGGER.debug(
                "Ignoring event from different device: %s (expected %s)",
                event_device_id,
                self.device_id,
            )
            return

        if self._state != STATE_ARMED:
            _LOGGER.warning(
                "Received learned event but session not armed (state: %s)", self._state
            )
            return

        # Validate payload
        carrier_hz = data.get(ATTR_CARRIER_HZ)
        timestamp = data.get(ATTR_TIMESTAMP, datetime.now().isoformat())

        # Parse pulses from JSON string (firmware sends pulses_json) or array
        pulses = []
        if ATTR_PULSES_JSON in data:
            try:
                pulses = json.loads(data[ATTR_PULSES_JSON])
            except (json.JSONDecodeError, TypeError) as err:
                _LOGGER.error("Failed to parse pulses_json: %s", err)
                asyncio.create_task(self._async_cancel("Invalid pulse data format"))
                return
        else:
            # Fallback to direct array (for testing or future firmware versions)
            pulses = data.get(ATTR_PULSES, [])

        if not isinstance(carrier_hz, int) or carrier_hz <= 0:
            _LOGGER.error("Invalid carrier_hz in learned event: %s", carrier_hz)
            asyncio.create_task(self._async_cancel("Invalid carrier frequency"))
            return

        if not isinstance(pulses, list) or len(pulses) == 0:
            _LOGGER.error("Invalid or empty pulses array in learned event")
            asyncio.create_task(self._async_cancel("Invalid pulse data"))
            return

        if len(pulses) > MAX_PULSE_ARRAY_LENGTH:
            _LOGGER.error(
                "Pulse array too large: %d (max: %d)",
                len(pulses),
                MAX_PULSE_ARRAY_LENGTH,
            )
            asyncio.create_task(
                self._async_cancel(f"Pulse array too large (max {MAX_PULSE_ARRAY_LENGTH})")
            )
            return

        # Store the learned code
        self._pending_code = LearnedCode(
            carrier_hz=carrier_hz,
            pulses=pulses,
            timestamp=timestamp,
            device_id=event_device_id,
        )

        _LOGGER.info(
            "Learned code captured: %d Hz, %d pulses", carrier_hz, len(pulses)
        )

        # Clean up and transition to RECEIVED state
        asyncio.create_task(self._async_finalize_learning())

    async def _async_finalize_learning(self) -> None:
        """Finalize learning after code received."""
        # Cancel timeout
        if self._timeout_handle:
            self._timeout_handle.cancel()
            self._timeout_handle = None

        # Disable learning mode
        try:
            await self.hass.services.async_call(
                "switch",
                "turn_off",
                {"entity_id": self.learning_switch_entity_id},
                blocking=True,
            )
        except Exception as err:
            _LOGGER.error("Failed to disable learning mode: %s", err)

        # Unsubscribe from events
        if self._event_listener:
            self._event_listener()
            self._event_listener = None

        self._state = STATE_RECEIVED
        self._notify_state_change()

    async def _async_handle_timeout(self) -> None:
        """Handle learning timeout."""
        if self._state != STATE_ARMED:
            return

        _LOGGER.warning("Learning session timed out after %d seconds", self.timeout)

        # Unsubscribe from events
        if self._event_listener:
            self._event_listener()
            self._event_listener = None

        # Disable learning mode
        try:
            await self.hass.services.async_call(
                "switch",
                "turn_off",
                {"entity_id": self.learning_switch_entity_id},
                blocking=True,
            )
        except Exception as err:
            _LOGGER.error("Failed to disable learning mode: %s", err)

        self._state = STATE_TIMEOUT
        self._notify_state_change()

    async def _async_cancel(self, reason: str) -> None:
        """Cancel the learning session."""
        _LOGGER.info("Cancelling learning session: %s", reason)

        # Cancel timeout
        if self._timeout_handle:
            self._timeout_handle.cancel()
            self._timeout_handle = None

        # Unsubscribe from events
        if self._event_listener:
            self._event_listener()
            self._event_listener = None

        # Disable learning mode
        try:
            await self.hass.services.async_call(
                "switch",
                "turn_off",
                {"entity_id": self.learning_switch_entity_id},
                blocking=True,
            )
        except Exception as err:
            _LOGGER.error("Failed to disable learning mode: %s", err)

        self._state = STATE_CANCELLED
        self._notify_state_change()

    def clear_pending(self) -> None:
        """Clear pending code and reset to idle."""
        self._pending_code = None
        self._state = STATE_IDLE
        self._notify_state_change()

    async def async_cleanup(self) -> None:
        """Clean up resources."""
        if self._timeout_handle:
            self._timeout_handle.cancel()
            self._timeout_handle = None

        if self._event_listener:
            self._event_listener()
            self._event_listener = None

        # Clear all callbacks to prevent orphaned references
        self._callbacks.clear()
