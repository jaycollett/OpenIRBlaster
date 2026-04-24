"""Learning session management for OpenIRBlaster."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.event import async_track_state_change_event

from .const import (
    ATTR_CARRIER_HZ,
    ATTR_DEVICE_ID,
    ATTR_MAC_ADDRESS,
    ATTR_PULSES,
    ATTR_PULSES_JSON,
    ATTR_TIMESTAMP,
    EVENT_LEARNED,
    LEARNING_TIMEOUT_SECONDS,
    MAX_PULSE_ARRAY_LENGTH,
    STATE_ARMED,
    STATE_CANCELLED,
    STATE_IDLE,
    STATE_RECEIVED,
    STATE_TIMEOUT,
)

# ESPHome firmware identifier for the payload text_sensor (id: last_ir_raw_snippet,
# name: "Last Learned IR (payload)"). The HA entity_id is slugified from the name.
_TEXT_SENSOR_OBJECT_ID_SUFFIX = "last_learned_ir_payload"
_TEXT_SENSOR_FIRMWARE_ID = "last_ir_raw_snippet"

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
        mac_address: str | None = None,
        timeout: int = LEARNING_TIMEOUT_SECONDS,
    ) -> None:
        """Initialize learning session.

        Args:
            hass: Home Assistant instance
            config_entry_id: The config entry ID
            device_id: ESPHome device name (e.g., "openirblaster-293aea")
            learning_switch_entity_id: Entity ID of the learning mode switch
            mac_address: Optional MAC address for stable device identification.
                If provided, events are filtered by MAC address first, then device_id.
            timeout: Learning timeout in seconds
        """
        self.hass = hass
        self.config_entry_id = config_entry_id
        self.device_id = device_id
        self.mac_address = mac_address
        self.learning_switch_entity_id = learning_switch_entity_id
        self.timeout = timeout

        self._state = STATE_IDLE
        self._pending_code: LearnedCode | None = None
        self._event_listener: Callable | None = None
        self._state_listener: Callable | None = None
        self._text_sensor_entity_id: str | None = None
        # Guards against the event and text-sensor fallback paths both firing
        # for the same learning capture (transient ESPHome API disconnect can
        # drop the event while the text_sensor state replays on reconnect).
        self._capture_finalized: bool = False
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
        _LOGGER.debug(
            "Notifying %d callbacks of state change to %s (pending_code: %s)",
            len(self._callbacks),
            self._state,
            self._pending_code is not None,
        )
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

        # Reset capture guard for the new session
        self._capture_finalized = False

        # Subscribe to learned events (primary path)
        self._event_listener = self.hass.bus.async_listen(
            EVENT_LEARNED, self._async_handle_learned_event
        )

        # Subscribe to the ESPHome payload text_sensor as a fallback. The
        # text_sensor state is resent when the ESPHome API reconnects, so it
        # survives transient socket drops that would otherwise swallow the
        # event. If the sensor cannot be resolved (e.g. device briefly offline
        # during setup) we just log and rely on the event path.
        self._text_sensor_entity_id = self._resolve_text_sensor_entity_id()
        if self._text_sensor_entity_id:
            _LOGGER.debug(
                "Subscribing to text_sensor fallback: %s", self._text_sensor_entity_id
            )
            self._state_listener = async_track_state_change_event(
                self.hass,
                [self._text_sensor_entity_id],
                self._async_handle_text_sensor_state,
            )
        else:
            _LOGGER.warning(
                "Could not resolve ESPHome payload text_sensor for device %s; "
                "learning will rely on event path only",
                self.device_id,
            )

        # Set timeout
        self._timeout_handle = self.hass.loop.call_later(
            self.timeout, lambda: asyncio.create_task(self._async_handle_timeout())
        )

        self._state = STATE_ARMED
        self._notify_state_change()
        return True

    def _resolve_text_sensor_entity_id(self) -> str | None:
        """Locate the ESPHome ``last_ir_raw_snippet`` text_sensor entity_id.

        Strategy (most robust first):
        1. If MAC is known, look up the ESPHome device in the HA device
           registry via its MAC connection, enumerate attached ``sensor``
           entities, and match by unique_id containing the firmware id or
           entity_id ending with the slugified object id.
        2. Fall back to a constructed entity_id pattern based on the ESPHome
           device name (hyphens -> underscores).

        Returns ``None`` if nothing matches; callers should log and continue
        without the fallback path.
        """
        try:
            ent_reg = er.async_get(self.hass)
        except Exception as err:  # defensive: registry should always exist
            _LOGGER.debug("Entity registry unavailable: %s", err)
            ent_reg = None

        # Strategy 1: device-registry lookup by MAC (stable across renames).
        if self.mac_address and ent_reg is not None:
            try:
                dev_reg = dr.async_get(self.hass)
                normalized_mac = self.mac_address.lower()
                ha_device = None
                for device in dev_reg.devices.values():
                    for conn_type, conn_value in device.connections:
                        if conn_type == dr.CONNECTION_NETWORK_MAC and conn_value.lower() == normalized_mac:
                            ha_device = device
                            break
                    if ha_device is not None:
                        break

                if ha_device is not None:
                    for entity in er.async_entries_for_device(
                        ent_reg, ha_device.id, include_disabled_entities=False
                    ):
                        if entity.domain != "sensor":
                            continue
                        unique_id = (entity.unique_id or "").lower()
                        entity_id = entity.entity_id.lower()
                        if _TEXT_SENSOR_FIRMWARE_ID in unique_id:
                            return entity.entity_id
                        if entity_id.endswith(f"_{_TEXT_SENSOR_OBJECT_ID_SUFFIX}"):
                            return entity.entity_id
            except Exception as err:
                _LOGGER.debug(
                    "Text_sensor device-registry lookup failed: %s", err
                )

        # Strategy 2: pattern from ESPHome device name. ESPHome slugs the
        # device name by lowercasing and replacing non-word chars with "_".
        slug = self.device_id.lower().replace("-", "_")
        candidate = f"sensor.{slug}_{_TEXT_SENSOR_OBJECT_ID_SUFFIX}"
        if self.hass.states.get(candidate) is not None:
            return candidate
        if ent_reg is not None and ent_reg.async_get(candidate) is not None:
            return candidate

        return None

    @callback
    def _async_handle_text_sensor_state(self, event: Event) -> None:
        """Handle a state change on the ESPHome payload text_sensor.

        The text_sensor carries the same learned-code data as the event, but
        as a JSON object in the state string. This path exists because the
        ESPHome API socket can drop the event while the text_sensor state is
        replayed on reconnect.
        """
        if self._state != STATE_ARMED or self._capture_finalized:
            return

        new_state = event.data.get("new_state")
        if new_state is None:
            return

        payload = new_state.state
        if not payload or payload in ("unknown", "unavailable", ""):
            return

        _LOGGER.debug(
            "Received text_sensor state update (len=%d) for %s",
            len(payload),
            self._text_sensor_entity_id,
        )

        try:
            data = json.loads(payload)
        except (json.JSONDecodeError, TypeError) as err:
            _LOGGER.error(
                "Failed to parse text_sensor payload as JSON: %s", err
            )
            asyncio.create_task(
                self._async_cancel("Invalid text_sensor payload (JSON parse)")
            )
            return

        if not isinstance(data, dict):
            _LOGGER.error("Text_sensor payload is not a JSON object: %s", type(data))
            asyncio.create_task(self._async_cancel("Invalid text_sensor payload"))
            return

        # Apply the same device filtering as the event path. The payload
        # always includes device_id; MAC is not present in the text_sensor
        # blob today but device_id matching is still a correctness guard if
        # multiple devices are present.
        event_device_id = data.get(ATTR_DEVICE_ID, "")
        if self.mac_address is None:
            if event_device_id and event_device_id != self.device_id:
                _LOGGER.debug(
                    "Ignoring text_sensor payload from device %s (ours: %s)",
                    event_device_id,
                    self.device_id,
                )
                return

        self._process_capture_payload(
            carrier_hz=data.get(ATTR_CARRIER_HZ),
            pulses_raw=data.get(ATTR_PULSES),
            pulses_json=None,
            timestamp=data.get(ATTR_TIMESTAMP),
            source_device_id=event_device_id or self.device_id,
            source="text_sensor",
        )

    @callback
    def _async_handle_learned_event(self, event: Event) -> None:
        """Handle learned event from ESPHome device."""
        data = event.data
        _LOGGER.debug(
            "Received learned event with data: %s (session device_id: %s, mac: %s, state: %s)",
            data,
            self.device_id,
            self.mac_address,
            self._state,
        )

        # Filter by MAC address (preferred, stable) or device_id (fallback)
        # MAC address matching is case-insensitive
        event_device_id = data.get(ATTR_DEVICE_ID, "")
        event_mac_address = data.get(ATTR_MAC_ADDRESS, "")

        is_our_device = False
        mac_comparison_done = False

        # Priority 1: Match by MAC address if both sides have it
        if self.mac_address and event_mac_address:
            mac_comparison_done = True
            # Normalize both to lowercase for comparison
            if event_mac_address.lower() == self.mac_address.lower():
                is_our_device = True
                _LOGGER.debug(
                    "Event matched by MAC address: %s",
                    event_mac_address,
                )
            else:
                _LOGGER.debug(
                    "Event MAC %s does not match session MAC %s - rejecting",
                    event_mac_address,
                    self.mac_address,
                )

        # Priority 2: Fall back to device_id matching only if MAC comparison wasn't done
        # (i.e., either session or event doesn't have MAC address)
        if not is_our_device and not mac_comparison_done:
            if event_device_id == self.device_id:
                is_our_device = True
                _LOGGER.debug(
                    "Event matched by device_id: %s",
                    event_device_id,
                )
            else:
                _LOGGER.debug(
                    "Event device_id %s does not match session device_id %s",
                    event_device_id,
                    self.device_id,
                )

        if not is_our_device:
            _LOGGER.debug(
                "Ignoring event from different device (event device_id: %s, mac: %s)",
                event_device_id,
                event_mac_address,
            )
            return

        _LOGGER.info(
            "Received IR code from device %s (MAC: %s)",
            event_device_id,
            event_mac_address or "unknown",
        )

        if self._state != STATE_ARMED:
            _LOGGER.warning(
                "Received learned event but session not armed (state: %s)", self._state
            )
            return

        if self._capture_finalized:
            _LOGGER.debug(
                "Ignoring duplicate event after capture already finalized via "
                "fallback path"
            )
            return

        # Parse pulses from JSON string (firmware sends pulses_json) or array
        pulses_json = data.get(ATTR_PULSES_JSON)
        pulses_raw = data.get(ATTR_PULSES)
        self._process_capture_payload(
            carrier_hz=data.get(ATTR_CARRIER_HZ),
            pulses_raw=pulses_raw,
            pulses_json=pulses_json,
            timestamp=data.get(ATTR_TIMESTAMP),
            source_device_id=event_device_id,
            source="event",
        )

    def _process_capture_payload(
        self,
        *,
        carrier_hz,
        pulses_raw,
        pulses_json: str | None,
        timestamp: str | None,
        source_device_id: str,
        source: str,
    ) -> None:
        """Validate and commit a capture from either path.

        Shared by the event handler and the text_sensor state fallback so the
        two paths apply identical validation, timeout cleanup, and state
        transitions. Callers are responsible for device-filtering and for
        checking ``_capture_finalized`` before invoking.
        """
        if self._capture_finalized:
            # Belt-and-suspenders: each caller already guards, but re-check
            # to be safe against races between the two async paths.
            return

        # Parse pulses: prefer JSON string form (event path), fall back to
        # direct array (text_sensor path or future firmware variants).
        pulses: list[int]
        if pulses_json is not None:
            try:
                pulses = json.loads(pulses_json)
            except (json.JSONDecodeError, TypeError) as err:
                _LOGGER.error("Failed to parse pulses_json: %s", err)
                asyncio.create_task(
                    self._async_cancel("Invalid pulse data format")
                )
                return
        elif pulses_raw is not None:
            pulses = pulses_raw
        else:
            _LOGGER.error("No pulses found in %s payload", source)
            asyncio.create_task(self._async_cancel("Missing pulse data"))
            return

        # Convert carrier_hz to int if it's a string (ESPHome may send as string)
        if isinstance(carrier_hz, str):
            try:
                carrier_hz = int(carrier_hz)
            except (ValueError, TypeError):
                _LOGGER.error("Cannot convert carrier_hz to int: %s", carrier_hz)
                asyncio.create_task(self._async_cancel("Invalid carrier frequency"))
                return

        if not isinstance(carrier_hz, int) or carrier_hz <= 0:
            _LOGGER.error(
                "Invalid carrier_hz in %s payload: %s", source, carrier_hz
            )
            asyncio.create_task(self._async_cancel("Invalid carrier frequency"))
            return

        if not isinstance(pulses, list) or len(pulses) == 0:
            _LOGGER.error("Invalid or empty pulses array in %s payload", source)
            asyncio.create_task(self._async_cancel("Invalid pulse data"))
            return

        if len(pulses) > MAX_PULSE_ARRAY_LENGTH:
            _LOGGER.error(
                "Pulse array too large (%s): %d (max: %d)",
                source,
                len(pulses),
                MAX_PULSE_ARRAY_LENGTH,
            )
            asyncio.create_task(
                self._async_cancel(
                    f"Pulse array too large (max {MAX_PULSE_ARRAY_LENGTH})"
                )
            )
            return

        # Commit capture. Mark finalized immediately so the other path bails
        # out if it arrives between here and the async finalizer task.
        self._capture_finalized = True
        self._pending_code = LearnedCode(
            carrier_hz=carrier_hz,
            pulses=pulses,
            timestamp=timestamp or datetime.now(timezone.utc).isoformat(),
            device_id=source_device_id,
        )

        _LOGGER.info(
            "Learned code captured via %s: %d Hz, %d pulses",
            source,
            carrier_hz,
            len(pulses),
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

        # Unsubscribe from both primary (event) and fallback (text_sensor) paths
        if self._event_listener:
            self._event_listener()
            self._event_listener = None
        if self._state_listener:
            self._state_listener()
            self._state_listener = None

        self._state = STATE_RECEIVED
        self._notify_state_change()

        # Create persistent notification to prompt user to save the code
        if self._pending_code:
            notification_message = (
                f"**New IR code learned!**\n\n"
                f"- Carrier: {self._pending_code.carrier_hz} Hz\n"
                f"- Pulses: {len(self._pending_code.pulses)}\n"
                f"- Timestamp: {self._pending_code.timestamp}\n\n"
                f"**To save this code:**\n"
                f"1. Go to Settings → Devices & Services\n"
                f"2. Find OpenIRBlaster integration\n"
                f"3. Click the device name\n"
                f"4. The pending code will be shown\n\n"
                f"Or use the **Send Last Learned** button to test it first!"
            )

            await self.hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "notification_id": f"openirblaster_learned_{self.config_entry_id}",
                    "title": "OpenIRBlaster - Code Learned",
                    "message": notification_message,
                },
            )

    async def _async_handle_timeout(self) -> None:
        """Handle learning timeout."""
        if self._state != STATE_ARMED:
            return

        _LOGGER.warning("Learning session timed out after %d seconds", self.timeout)

        # Unsubscribe from both listener paths
        if self._event_listener:
            self._event_listener()
            self._event_listener = None
        if self._state_listener:
            self._state_listener()
            self._state_listener = None

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

        # Unsubscribe from both listener paths
        if self._event_listener:
            self._event_listener()
            self._event_listener = None
        if self._state_listener:
            self._state_listener()
            self._state_listener = None

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

    async def async_clear_pending(self) -> None:
        """Clear pending code and reset to idle.

        Idempotent and safe to call from any state. In addition to clearing
        ``_pending_code`` and returning to ``STATE_IDLE``, this also cancels
        any lingering timeout handle and tears down both listener paths so
        that a subsequent ``async_start_learning`` starts from a clean slate.
        This protects against prior sessions that ended in ``TIMEOUT`` /
        ``CANCELLED`` / ``RECEIVED`` states and never finalized their
        listeners due to an error path.
        """
        # Dismiss the notification
        await self.hass.services.async_call(
            "persistent_notification",
            "dismiss",
            {
                "notification_id": f"openirblaster_learned_{self.config_entry_id}",
            },
        )

        # Cancel any lingering timeout handle
        if self._timeout_handle:
            self._timeout_handle.cancel()
            self._timeout_handle = None

        # Unsubscribe both listener paths if still registered
        if self._event_listener:
            self._event_listener()
            self._event_listener = None
        if self._state_listener:
            self._state_listener()
            self._state_listener = None

        self._pending_code = None
        self._capture_finalized = False
        self._state = STATE_IDLE
        self._notify_state_change()

    def clear_pending(self) -> None:
        """Clear pending code and reset to idle (sync wrapper)."""
        asyncio.create_task(self.async_clear_pending())

    async def async_cleanup(self) -> None:
        """Clean up resources."""
        if self._timeout_handle:
            self._timeout_handle.cancel()
            self._timeout_handle = None

        if self._event_listener:
            self._event_listener()
            self._event_listener = None

        if self._state_listener:
            self._state_listener()
            self._state_listener = None

        # Clear all callbacks to prevent orphaned references
        self._callbacks.clear()
