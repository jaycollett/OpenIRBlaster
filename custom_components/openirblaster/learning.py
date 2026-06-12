"""Learning session management for OpenIRBlaster."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers import (
    device_registry as dr,
    entity_registry as er,
    issue_registry as ir,
)
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
)

from .const import (
    ATTR_CARRIER_HZ,
    ATTR_DEVICE_ID,
    ATTR_MAC_ADDRESS,
    ATTR_PULSES_JSON,
    ATTR_TIMESTAMP,
    DOMAIN,
    EVENT_LEARNED,
    LEARNING_TIMEOUT_SECONDS,
    MAX_PULSE_ARRAY_LENGTH,
    STATE_ARMED,
    STATE_CANCELLED,
    STATE_IDLE,
    STATE_RECEIVED,
    STATE_TIMEOUT,
)
from .helpers import get_esphome_service

# ESPHome firmware identifier for the capture-marker text_sensor (id and
# slugified name both equal "last_ir_capture_marker"). The marker carries
# only a short timestamp string -- it deliberately stays under HA core's
# 255-char state-length limit so the state change survives the bus. When
# this state changes we use it as a hint to ask the firmware to replay
# the learned event in case the original was lost on a transient API drop.
_CAPTURE_MARKER_OBJECT_ID_SUFFIX = "last_ir_capture_marker"
_CAPTURE_MARKER_FIRMWARE_ID = "last_ir_capture_marker"

# How long to wait for the original learned event after seeing the marker
# state change. The event normally arrives within milliseconds; the only
# reason it would not is a dropped API socket between event emission and
# HA's bus, which is exactly what the replay path is built to recover.
_REPLAY_GRACE_SECONDS = 0.5

# Suffix the firmware uses for both ESPHome API services so we can derive
# the replay service name from the cached send_ir_raw service name without
# a second discovery pass.
_SEND_SERVICE_SUFFIX = "_send_ir_raw"
_REPLAY_SERVICE_SUFFIX = "_replay_last_ir"

# Colon-separated hex MAC like "AA:BB:CC:DD:EE:FF". Older firmware versions
# returned a dangling-pointer c_str() in the on_raw lambda, so the event MAC
# field would arrive as a few bytes of stale heap memory instead of a real
# MAC. We use this to detect that case and fall back to device_id matching.
_MAC_ADDRESS_RE = re.compile(r"^[0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5}$")

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
        # Guards against the event and replay paths both committing a capture
        # for the same session. A transient ESPHome API disconnect can drop
        # the original event while the marker text_sensor state replays on
        # reconnect; that replay triggers replay_last_ir, which re-fires the
        # event. Once one path finalizes, the other has to bail.
        self._capture_finalized: bool = False
        # Cancel callable returned by async_call_later for the session
        # timeout. Call it (via _cancel_timeout) to cancel the deadline.
        self._timeout_unsub: CALLBACK_TYPE | None = None
        # Pending wait-then-replay tasks scheduled from the marker handler.
        # Tracked so session teardown can cancel them, otherwise we'd leak
        # 500ms-pending tasks that hold a reference to this session.
        self._pending_replay_tasks: set[asyncio.Task] = set()
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

    async def async_start_learning(self, timeout: int | None = None) -> bool:
        """Start a learning session.

        Args:
            timeout: Optional per-session timeout override in seconds. When
                None, the session default (``self.timeout``) is used. The
                override applies to this session only and does not change
                the default for subsequent sessions.
        """
        if self._state != STATE_IDLE:
            _LOGGER.warning(
                "Cannot start learning: session already in state %s", self._state
            )
            return False

        # Claim the session synchronously, before the first await, so a
        # concurrent start hits the IDLE check above and is rejected.
        # Without this, two starts could both pass the check; the second
        # would overwrite the first's listener unsubscribe callable and
        # leak that bus subscription permanently.
        self._state = STATE_ARMED
        self._capture_finalized = False

        session_timeout = timeout if timeout is not None else self.timeout

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
            # Release the claim. Nothing else was registered yet, so
            # reverting the state is the only cleanup needed.
            self._state = STATE_IDLE
            return False

        # Subscribe to learned events (primary path)
        self._event_listener = self.hass.bus.async_listen(
            EVENT_LEARNED, self._async_handle_learned_event
        )

        # Subscribe to the capture-marker text_sensor. The marker's state
        # changes after every learned capture and the value replays on API
        # reconnect; if the original event was lost on a transient socket
        # drop we use the state change as a hint to call replay_last_ir.
        self._text_sensor_entity_id = self._resolve_text_sensor_entity_id()
        if self._text_sensor_entity_id:
            _LOGGER.debug(
                "Subscribing to capture marker: %s", self._text_sensor_entity_id
            )
            self._state_listener = async_track_state_change_event(
                self.hass,
                [self._text_sensor_entity_id],
                self._async_handle_capture_marker_change,
            )
        else:
            _LOGGER.warning(
                "Could not resolve capture marker text_sensor for device %s; "
                "learning will rely on event path only",
                self.device_id,
            )

        # Set timeout. async_call_later returns a cancel callable and runs
        # the coroutine as an HA-tracked job when the deadline fires.
        self._timeout_unsub = async_call_later(
            self.hass, session_timeout, self._async_handle_timeout
        )

        # State was claimed (ARMED) before the first await; notify now that
        # the session is fully armed.
        self._notify_state_change()
        return True

    def _cancel_timeout(self) -> None:
        """Cancel the scheduled learning timeout, if any. Idempotent."""
        if self._timeout_unsub:
            self._timeout_unsub()
            self._timeout_unsub = None

    def _resolve_text_sensor_entity_id(self) -> str | None:
        """Locate the capture-marker text_sensor entity_id.

        Strategy (most robust first):
        1. If MAC is known, look up the ESPHome device in the HA device
           registry via its MAC connection, enumerate attached ``sensor``
           entities, and match by unique_id containing the firmware id or
           entity_id ending with the slugified object id.
        2. Fall back to a constructed entity_id pattern based on the ESPHome
           device name (hyphens -> underscores).

        Returns ``None`` if nothing matches; callers should log and continue
        without the replay safety net.
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
                        if _CAPTURE_MARKER_FIRMWARE_ID in unique_id:
                            return entity.entity_id
                        if entity_id.endswith(f"_{_CAPTURE_MARKER_OBJECT_ID_SUFFIX}"):
                            return entity.entity_id
            except Exception as err:
                _LOGGER.debug(
                    "Capture marker device-registry lookup failed: %s", err
                )

        # Strategy 2: pattern from ESPHome device name. ESPHome slugs the
        # device name by lowercasing and replacing non-word chars with "_".
        slug = self.device_id.lower().replace("-", "_")
        candidate = f"sensor.{slug}_{_CAPTURE_MARKER_OBJECT_ID_SUFFIX}"
        if self.hass.states.get(candidate) is not None:
            return candidate
        if ent_reg is not None and ent_reg.async_get(candidate) is not None:
            return candidate

        return None

    @callback
    def _async_handle_capture_marker_change(self, event: Event) -> None:
        """React to a state change on the capture-marker text_sensor.

        The marker changes after every learned capture and the value
        survives an API reconnect, which gives us a hook to detect a lost
        event. We arm a short grace timer; if the corresponding learned
        event arrives within that window the timer is a no-op, otherwise
        we call replay_last_ir on the device to re-fire the event.
        """
        # Defensive: if cleanup has already torn down the state listener
        # but we somehow still got dispatched (race during shutdown), don't
        # schedule a wait task into a closing loop.
        if self._state_listener is None:
            return
        if self._state != STATE_ARMED or self._capture_finalized:
            return

        new_state = event.data.get("new_state")
        if new_state is None:
            return

        marker = new_state.state
        if not marker or marker in ("unknown", "unavailable"):
            return

        _LOGGER.debug(
            "Capture marker changed to %r on %s; arming replay grace timer",
            marker,
            self._text_sensor_entity_id,
        )

        # Background task: HA tracks it for shutdown, but block_till_done
        # does not wait on it (the grace sleep would stall the event loop
        # drain otherwise). The local set still drives replay-drain logic.
        task = self.hass.async_create_background_task(
            self._async_wait_then_request_replay(marker),
            name=f"openirblaster_replay_wait_{self.config_entry_id}",
        )
        self._pending_replay_tasks.add(task)
        task.add_done_callback(self._pending_replay_tasks.discard)

    async def _async_wait_then_request_replay(self, marker: str) -> None:
        """Wait the grace period, then request a replay if no event arrived."""
        try:
            await asyncio.sleep(_REPLAY_GRACE_SECONDS)
        except asyncio.CancelledError:
            return

        if self._capture_finalized or self._state != STATE_ARMED:
            # The event path already finalized this session, or the session
            # ended (timed out, cancelled, cleared). Nothing to do.
            return

        _LOGGER.warning(
            "Capture marker %r observed but no learned event arrived within "
            "%.1fs; requesting replay from device",
            marker,
            _REPLAY_GRACE_SECONDS,
        )
        await self._async_request_replay()

    async def _async_request_replay(self) -> None:
        """Call the device's replay_last_ir service to re-fire the event."""
        send_service = get_esphome_service(self.hass, self.config_entry_id)
        if not send_service or not send_service.endswith(_SEND_SERVICE_SUFFIX):
            _LOGGER.error(
                "Cannot request replay: send_ir_raw service is %r, "
                "expected a name ending in %r",
                send_service,
                _SEND_SERVICE_SUFFIX,
            )
            return

        replay_service = (
            send_service[: -len(_SEND_SERVICE_SUFFIX)] + _REPLAY_SERVICE_SUFFIX
        )

        try:
            await self.hass.services.async_call(
                "esphome",
                replay_service,
                {},
                blocking=False,
            )
        except Exception as err:
            _LOGGER.error(
                "Failed to call replay service %s: %s", replay_service, err
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

        # Older firmware versions returned a dangling-pointer c_str() in the
        # on_raw lambda, so the event MAC could arrive as a few bytes of stale
        # heap memory rather than a real address. Detect that case and treat
        # the event as if no MAC was supplied so device_id matching kicks in
        # rather than silently dropping the event.
        if event_mac_address and not _MAC_ADDRESS_RE.fullmatch(event_mac_address):
            _LOGGER.warning(
                "Event MAC %r is not a valid AA:BB:CC:DD:EE:FF address. "
                "Device firmware likely needs to be updated. "
                "Falling back to device_id matching for this event.",
                event_mac_address,
            )
            # Surface a repair: this is a known bug in older firmware and
            # the user can fix it by updating the device.
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                f"dangling_mac_{self.config_entry_id}",
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key="dangling_mac",
                translation_placeholders={"device_id": self.device_id},
            )
            event_mac_address = ""
        elif event_mac_address:
            # Firmware is emitting valid MACs; clear any stale repair from
            # a pre-update capture.
            ir.async_delete_issue(
                self.hass, DOMAIN, f"dangling_mac_{self.config_entry_id}"
            )

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
                "Ignoring duplicate event after capture already finalized"
            )
            return

        self._process_capture_payload(
            carrier_hz=data.get(ATTR_CARRIER_HZ),
            pulses_json=data.get(ATTR_PULSES_JSON),
            timestamp=data.get(ATTR_TIMESTAMP),
            source_device_id=event_device_id,
        )

    def _process_capture_payload(
        self,
        *,
        carrier_hz,
        pulses_json: str | None,
        timestamp: str | None,
        source_device_id: str,
    ) -> None:
        """Validate and commit a captured learned event.

        Caller is responsible for device-filtering and for checking
        ``_capture_finalized`` before invoking. Sets ``_capture_finalized``
        atomically before any await so a concurrent replay event finds it
        set and bails.
        """
        if self._capture_finalized:
            # Belt-and-suspenders: caller already guards, but re-check in
            # case a replay event arrived between caller's check and here.
            return

        if not pulses_json:
            _LOGGER.error("Event payload missing pulses_json")
            self._capture_finalized = True
            self.hass.async_create_task(self._async_cancel("Missing pulse data"))
            return

        try:
            pulses = json.loads(pulses_json)
        except (json.JSONDecodeError, TypeError) as err:
            _LOGGER.error("Failed to parse pulses_json: %s", err)
            self._capture_finalized = True
            self.hass.async_create_task(
                self._async_cancel("Invalid pulse data format")
            )
            return

        # Convert carrier_hz to int if it's a string (ESPHome may send as string)
        if isinstance(carrier_hz, str):
            try:
                carrier_hz = int(carrier_hz)
            except (ValueError, TypeError):
                _LOGGER.error("Cannot convert carrier_hz to int: %s", carrier_hz)
                self._capture_finalized = True
                self.hass.async_create_task(
                    self._async_cancel("Invalid carrier frequency")
                )
                return

        if not isinstance(carrier_hz, int) or carrier_hz <= 0:
            _LOGGER.error("Invalid carrier_hz in event payload: %s", carrier_hz)
            self._capture_finalized = True
            self.hass.async_create_task(
                self._async_cancel("Invalid carrier frequency")
            )
            return

        if not isinstance(pulses, list) or len(pulses) == 0:
            _LOGGER.error("Invalid or empty pulses array in event payload")
            self._capture_finalized = True
            self.hass.async_create_task(self._async_cancel("Invalid pulse data"))
            return

        if len(pulses) > MAX_PULSE_ARRAY_LENGTH:
            _LOGGER.error(
                "Pulse array too large: %d (max: %d)",
                len(pulses),
                MAX_PULSE_ARRAY_LENGTH,
            )
            self._capture_finalized = True
            self.hass.async_create_task(
                self._async_cancel(
                    f"Pulse array too large (max {MAX_PULSE_ARRAY_LENGTH})"
                )
            )
            return

        # Commit capture. Mark finalized immediately so a replay event that
        # races in between here and the async finalizer task bails out.
        self._capture_finalized = True
        # Cancel the timeout synchronously. The finalize task below also
        # cancels it (harmless/idempotent), but that task may not run before
        # the deadline fires; without this, a capture landing right at the
        # deadline could let the timeout path emit a spurious TIMEOUT state.
        self._cancel_timeout()
        self._pending_code = LearnedCode(
            carrier_hz=carrier_hz,
            pulses=pulses,
            timestamp=timestamp or datetime.now(timezone.utc).isoformat(),
            device_id=source_device_id,
        )

        _LOGGER.info(
            "Learned code captured: %d Hz, %d pulses",
            carrier_hz,
            len(pulses),
        )

        # Clean up and transition to RECEIVED state
        self.hass.async_create_task(self._async_finalize_learning())

    def _cancel_pending_replay_tasks(self) -> None:
        """Cancel any in-flight wait-then-replay tasks scheduled by the marker."""
        if not self._pending_replay_tasks:
            return
        for task in list(self._pending_replay_tasks):
            if not task.done():
                task.cancel()
        self._pending_replay_tasks.clear()

    async def _async_finalize_learning(self) -> None:
        """Finalize learning after code received."""
        # Cancel timeout (idempotent; already cancelled at the commit site)
        self._cancel_timeout()

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

        # Unsubscribe from primary (event) and marker (state) paths, and
        # cancel any wait-then-replay task that may still be pending.
        if self._event_listener:
            self._event_listener()
            self._event_listener = None
        if self._state_listener:
            self._state_listener()
            self._state_listener = None
        self._cancel_pending_replay_tasks()

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

    async def _async_handle_timeout(self, _now: datetime | None = None) -> None:
        """Handle learning timeout.

        Args:
            _now: Fired-at datetime supplied by async_call_later; unused.
        """
        # _capture_finalized guards the race where a capture lands just
        # before the deadline (or while finalize is suspended awaiting the
        # switch turn-off): the session is still ARMED at that instant, but
        # the capture has won and the timeout path must be a no-op.
        if self._state != STATE_ARMED or self._capture_finalized:
            return

        _LOGGER.warning("Learning session timed out after %d seconds", self.timeout)

        # Unsubscribe listeners and cancel any pending replay task.
        if self._event_listener:
            self._event_listener()
            self._event_listener = None
        if self._state_listener:
            self._state_listener()
            self._state_listener = None
        self._cancel_pending_replay_tasks()

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
        self._cancel_timeout()

        # Unsubscribe listeners and cancel any pending replay task.
        if self._event_listener:
            self._event_listener()
            self._event_listener = None
        if self._state_listener:
            self._state_listener()
            self._state_listener = None
        self._cancel_pending_replay_tasks()

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

        # Surface the cancel to the user. Validation failures (bad JSON,
        # bogus carrier, oversized pulse array) are silent otherwise; users
        # need a UI hint so they know the press produced garbage and that the
        # device firmware may need attention. Uses a distinct notification_id
        # so it doesn't collide with the "Code Learned" success notification.
        try:
            await self.hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "notification_id": (
                        f"openirblaster_cancelled_{self.config_entry_id}"
                    ),
                    "title": "OpenIRBlaster - Learning Cancelled",
                    "message": (
                        f"Learning cancelled: {reason}. This usually indicates "
                        f"a firmware issue - check the device log."
                    ),
                },
            )
        except Exception as err:
            _LOGGER.debug("Failed to create cancel notification: %s", err)

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
        # Dismiss both the "code learned" success notification and the
        # "learning cancelled" failure notification. Either may be stale and
        # we don't want them lingering past an explicit dismissal.
        await self.hass.services.async_call(
            "persistent_notification",
            "dismiss",
            {
                "notification_id": f"openirblaster_learned_{self.config_entry_id}",
            },
        )
        await self.hass.services.async_call(
            "persistent_notification",
            "dismiss",
            {
                "notification_id": (
                    f"openirblaster_cancelled_{self.config_entry_id}"
                ),
            },
        )

        # Cancel any lingering timeout
        self._cancel_timeout()

        # Unsubscribe listeners and cancel any pending replay task.
        if self._event_listener:
            self._event_listener()
            self._event_listener = None
        if self._state_listener:
            self._state_listener()
            self._state_listener = None
        self._cancel_pending_replay_tasks()

        self._pending_code = None
        self._capture_finalized = False
        self._state = STATE_IDLE
        self._notify_state_change()

    async def async_cleanup(self) -> None:
        """Clean up resources."""
        self._cancel_timeout()

        if self._event_listener:
            self._event_listener()
            self._event_listener = None

        if self._state_listener:
            self._state_listener()
            self._state_listener = None

        self._cancel_pending_replay_tasks()

        # Clear all callbacks to prevent orphaned references
        self._callbacks.clear()
