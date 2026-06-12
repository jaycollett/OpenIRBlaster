"""The OpenIRBlaster integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import (
    config_validation as cv,
    device_registry as dr,
    entity_registry as er,
    issue_registry as ir,
)
from homeassistant.helpers.typing import ConfigType

from .const import (
    CONF_DEVICE_ID,
    CONF_LEARNING_SWITCH_ENTITY_ID,
    CONF_MAC_ADDRESS,
    DOMAIN,
    STATE_ARMED,
)
from .data import OpenIRBlasterConfigEntry, OpenIRBlasterData
from .helpers import (
    AmbiguousEsphomeServiceError,
    async_clear_send_service_missing,
    discover_esphome_service,
)
from .learning import LearningSession
from .services import async_setup_services
from .storage import OpenIRBlasterStorage

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.BUTTON, Platform.EVENT, Platform.SENSOR, Platform.TEXT]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the OpenIRBlaster integration (register services once)."""
    await async_setup_services(hass)
    return True


def _lookup_mac_from_esphome_device(
    hass: HomeAssistant, device_id: str, entry_id: str
) -> str | None:
    """Locate the MAC address of an ESPHome device from the HA device registry.

    Returns the MAC in its original HA format (typically lowercase colon-separated)
    if a single unambiguous ESPHome device matches ``device_id``; otherwise
    returns ``None`` (caller falls back to Strategy 2 slug resolution).

    Match precedence:
      1. Exact match on device name, name_by_user, or any identifier value
         (case-insensitive, with underscore/hyphen normalization).
      2. Substring match on the same fields, but only when a single candidate
         has a MAC connection. If multiple substring candidates carry MACs,
         we refuse to guess and return None.

    Only devices owned by the ``esphome`` integration are considered.
    """
    try:
        dev_reg = dr.async_get(hass)
    except Exception as err:  # pragma: no cover - registry should always exist
        _LOGGER.debug("Device registry unavailable during MAC lookup: %s", err)
        return None

    device_id_lower = device_id.lower()
    normalized_device_id = device_id_lower.replace("_", "-")
    targets = {device_id_lower, normalized_device_id}

    exact_matches: list[dr.DeviceEntry] = []
    substring_matches: list[dr.DeviceEntry] = []

    for device in dev_reg.devices.values():
        # Restrict to devices owned by the ESPHome integration.
        is_esphome = False
        for ce_id in device.config_entries:
            ce = hass.config_entries.async_get_entry(ce_id)
            if ce is not None and ce.domain == "esphome":
                is_esphome = True
                break
        if not is_esphome:
            continue

        name = (device.name or "").lower()
        name_by_user = (device.name_by_user or "").lower()
        ident_values = [str(ident[1]).lower() for ident in device.identifiers]

        # Exact match: any field equals one of the target forms.
        if (
            name in targets
            or (name_by_user and name_by_user in targets)
            or any(v in targets for v in ident_values)
        ):
            exact_matches.append(device)
            continue

        # Substring match: any field contains one of the target forms.
        def _contains(haystack: str) -> bool:
            return bool(haystack) and any(t in haystack for t in targets)

        if (
            _contains(name)
            or _contains(name_by_user)
            or any(_contains(v) for v in ident_values)
        ):
            substring_matches.append(device)

    def _first_mac(device: dr.DeviceEntry) -> str | None:
        for conn_type, conn_value in device.connections:
            if conn_type == dr.CONNECTION_NETWORK_MAC and conn_value:
                return conn_value
        return None

    # Prefer exact matches. If multiple exact matches carry MACs, refuse to
    # guess -- log and fall through to return None.
    exact_with_mac = [
        (d, mac) for d in exact_matches if (mac := _first_mac(d)) is not None
    ]
    if len(exact_with_mac) == 1:
        return exact_with_mac[0][1]
    if len(exact_with_mac) > 1:
        _LOGGER.warning(
            "Multiple ESPHome devices exactly match '%s' and carry MAC "
            "connections (%d candidates). Skipping MAC back-fill to avoid "
            "assigning the wrong one.",
            device_id,
            len(exact_with_mac),
        )
        _async_flag_ambiguous_backfill(hass, entry_id, device_id)
        return None

    # Fall back to substring matches only when unambiguous.
    substring_with_mac = [
        (d, mac) for d in substring_matches if (mac := _first_mac(d)) is not None
    ]
    if len(substring_with_mac) == 1:
        return substring_with_mac[0][1]
    if len(substring_with_mac) > 1:
        _LOGGER.warning(
            "Multiple ESPHome devices fuzzy-match '%s' and carry MAC "
            "connections (%d candidates). Skipping MAC back-fill to avoid "
            "assigning the wrong one. If the text_sensor fallback is "
            "unreliable, remove and re-add the integration so the config "
            "flow can capture the correct MAC.",
            device_id,
            len(substring_with_mac),
        )
        _async_flag_ambiguous_backfill(hass, entry_id, device_id)
        return None

    return None


def _async_flag_ambiguous_backfill(
    hass: HomeAssistant, entry_id: str, device_id: str
) -> None:
    """Raise a repair: the MAC back-fill matcher cannot pick a device."""
    ir.async_create_issue(
        hass,
        DOMAIN,
        f"ambiguous_mac_backfill_{entry_id}",
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key="ambiguous_mac_backfill",
        translation_placeholders={"device_id": device_id},
    )


def _async_migrate_controls_device(
    hass: HomeAssistant, base_identifiers: set[str], main_device_id: str
) -> None:
    """Remove the legacy virtual "Controls" device (pre-1.2 layout).

    Older versions grouped management entities on a second registry device
    keyed by f"{base}_controls". Those entities now live on the main
    device with entity categories. Re-point any entity registry entries
    still attached to a Controls device first (removing a device would
    delete its entities' registry entries, losing user customizations),
    then remove the Controls device itself.

    Sweeps every candidate base identifier: a pre-MAC install created its
    Controls device under the device_id identifier, and a MAC back-filled
    on the upgrade boot would otherwise orphan {device_id}_controls.

    Idempotent: a no-op when no Controls device exists.
    """
    device_registry = dr.async_get(hass)
    entity_registry = er.async_get(hass)

    for base_identifier in base_identifiers:
        controls_device = device_registry.async_get_device(
            identifiers={(DOMAIN, f"{base_identifier}_controls")}
        )
        if controls_device is None:
            continue

        for entity in er.async_entries_for_device(
            entity_registry, controls_device.id, include_disabled_entities=True
        ):
            _LOGGER.debug(
                "Re-pointing entity %s from Controls device to main device",
                entity.entity_id,
            )
            entity_registry.async_update_entity(
                entity.entity_id, device_id=main_device_id
            )

        _LOGGER.info(
            "Removing legacy Controls device %s (entities migrated to main device)",
            controls_device.id,
        )
        device_registry.async_remove_device(controls_device.id)


async def async_setup_entry(
    hass: HomeAssistant, entry: OpenIRBlasterConfigEntry
) -> bool:
    """Set up OpenIRBlaster from a config entry."""
    _LOGGER.info("Setting up OpenIRBlaster integration for entry %s", entry.entry_id)

    device_id = entry.data[CONF_DEVICE_ID]
    mac_address = entry.data.get(CONF_MAC_ADDRESS)

    # Issue #8 follow-up: older config entries that predate MAC capture have
    # no MAC recorded. That breaks the text_sensor fallback's Strategy 1
    # (device-registry lookup by MAC) and leaves those installs with only
    # the fragile slug-based Strategy 2. Back-fill MAC from the ESPHome
    # device in the HA device registry so existing installs gain the robust
    # resolver path without requiring the user to remove and re-add the
    # integration.
    if not mac_address:
        backfilled_mac = _lookup_mac_from_esphome_device(
            hass, device_id, entry.entry_id
        )
        if backfilled_mac:
            _LOGGER.info(
                "Back-filled MAC address %s for device %s from ESPHome device "
                "registry entry",
                backfilled_mac,
                device_id,
            )
            new_data = {**entry.data, CONF_MAC_ADDRESS: backfilled_mac}
            hass.config_entries.async_update_entry(entry, data=new_data)
            mac_address = backfilled_mac
        else:
            _LOGGER.warning(
                "MAC address not configured for device %s and no matching "
                "ESPHome device found in the device registry. Text_sensor "
                "fallback will rely on slug heuristics only.",
                device_id,
            )

    if mac_address:
        # A MAC is known (stored or just back-filled), so any earlier
        # ambiguous-back-fill repair is resolved.
        ir.async_delete_issue(
            hass, DOMAIN, f"ambiguous_mac_backfill_{entry.entry_id}"
        )

    # Discover the ESPHome service name before building any state. If the
    # device is not online yet (its API services are not registered), raise
    # ConfigEntryNotReady so HA retries setup with backoff. Raising here,
    # before storage and the learning session exist, means no cleanup is
    # needed on this path.
    try:
        esphome_service_name = discover_esphome_service(hass, entry)
    except AmbiguousEsphomeServiceError as err:
        raise ConfigEntryNotReady(
            f"Multiple ESPHome send_ir_raw services could belong to device "
            f"{device_id} and none can be verified as its own. Reconfigure "
            "the integration to bind the correct device."
        ) from err
    if not esphome_service_name:
        raise ConfigEntryNotReady(
            f"ESPHome send_ir_raw service for device {device_id} is not yet "
            "available; is the device online?"
        )

    # Discovery succeeded: any lingering missing-service repair from a
    # failed send is resolved (mirrors the ambiguous-back-fill clearing).
    async_clear_send_service_missing(hass, entry.entry_id)

    # Initialize storage
    storage = OpenIRBlasterStorage(hass, entry.entry_id)
    await storage.async_load()

    # Update device info in storage
    await storage.async_update_device_info(device_id)

    # Initialize learning session with MAC address for stable event filtering
    learning_session = LearningSession(
        hass,
        entry.entry_id,
        device_id,
        entry.data[CONF_LEARNING_SWITCH_ENTITY_ID],
        mac_address=mac_address,
    )

    # Determine device identifier: prefer MAC address (stable), fall back to device_id
    # This ensures the device registry entry stays stable even if ESPHome device name changes
    if mac_address:
        # Normalize MAC: lowercase, no colons (e.g., "aabbccddeeff")
        normalized_mac = mac_address.lower().replace(":", "")
        device_identifier = normalized_mac
        _LOGGER.debug(
            "Using MAC-based device identifier %s for device %s",
            device_identifier,
            device_id,
        )
    else:
        device_identifier = device_id
        _LOGGER.debug(
            "MAC address not available, using device_id as identifier: %s",
            device_identifier,
        )

    # Register the single main device. Management entities are grouped via
    # entity_category (CONFIG/DIAGNOSTIC) on this device; the old virtual
    # "Controls" device is gone (see _async_migrate_controls_device).
    device_registry = dr.async_get(hass)

    # Main physical ESPHome device
    # Use MAC-based identifier if available for stability across ESPHome YAML changes
    main_device = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, device_identifier)},
        name=f"OpenIRBlaster {device_id}",
        manufacturer="OpenIRBlaster",
        model="ESP8266 IR Blaster",
    )

    # One-time migration: remove the legacy virtual "Controls" device.
    # Sweep both the current (possibly MAC-based) identifier and the
    # device_id identifier, covering pre-MAC installs whose MAC was only
    # back-filled on this boot.
    _async_migrate_controls_device(
        hass, {device_identifier, device_id}, main_device.id
    )

    # Store runtime objects on the config entry
    entry.runtime_data = OpenIRBlasterData(
        storage=storage,
        learning_session=learning_session,
        esphome_service_name=esphome_service_name,
    )

    # Best-effort: a previous run interrupted while ARMED can leave the
    # device stuck in learning mode. Turn it off in the background so an
    # offline or slow device cannot delay setup; failures are swallowed.
    learning_switch_entity_id = entry.data[CONF_LEARNING_SWITCH_ENTITY_ID]
    switch_state = hass.states.get(learning_switch_entity_id)
    if switch_state is not None and switch_state.state == "on":

        async def _async_reset_learning_switch() -> None:
            # Re-check at execution time: a user (or boot automation) may
            # have armed a session between scheduling and execution; a
            # delayed turn-off must never disarm an active session.
            if learning_session.state == STATE_ARMED:
                _LOGGER.debug(
                    "Skipping learning-mode reset: a session is armed"
                )
                return
            try:
                await hass.services.async_call(
                    "switch",
                    "turn_off",
                    {"entity_id": learning_switch_entity_id},
                    blocking=True,
                )
                _LOGGER.info(
                    "Reset learning mode left on from a previous run (%s)",
                    learning_switch_entity_id,
                )
            except Exception as err:
                _LOGGER.debug(
                    "Best-effort learning-mode reset failed: %s", err
                )

        entry.async_create_background_task(
            hass,
            _async_reset_learning_switch(),
            name=f"openirblaster_learning_reset_{entry.entry_id}",
        )

    # Set up platforms. On failure, tear down the learning session so
    # nothing leaks for the failed entry, then re-raise so HA records the
    # setup error.
    try:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except Exception:
        await learning_session.async_cleanup()
        raise

    # Note: No update listener needed - our integration doesn't have options that require reload
    # Config entry rename is handled automatically by Home Assistant core

    _LOGGER.info("OpenIRBlaster integration setup complete for entry %s", entry.entry_id)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: OpenIRBlasterConfigEntry
) -> bool:
    """Unload a config entry."""
    _LOGGER.info("Unloading OpenIRBlaster integration for entry %s", entry.entry_id)

    # Unload platforms
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        # Clean up learning session
        await entry.runtime_data.learning_session.async_cleanup()

    return unload_ok


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle removal of a config entry (delete its storage file)."""
    _LOGGER.info("Removing OpenIRBlaster config entry %s", entry.entry_id)

    # Delete storage file for this entry. Device and entity registry
    # entries are removed automatically by core when the entry is removed.
    storage = OpenIRBlasterStorage(hass, entry.entry_id)
    await storage.async_delete()

    _LOGGER.info("Cleanup complete for entry %s: storage deleted", entry.entry_id)
