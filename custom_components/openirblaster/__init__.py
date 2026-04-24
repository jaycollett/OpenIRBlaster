"""The OpenIRBlaster integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .const import (
    CONF_DEVICE_ID,
    CONF_LEARNING_SWITCH_ENTITY_ID,
    CONF_MAC_ADDRESS,
    DOMAIN,
)
from .helpers import discover_esphome_service
from .learning import LearningSession
from .services import async_setup_services, async_unload_services
from .storage import OpenIRBlasterStorage

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.BUTTON, Platform.SENSOR, Platform.TEXT]


def _lookup_mac_from_esphome_device(
    hass: HomeAssistant, device_id: str
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
        return None

    return None


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
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
        backfilled_mac = _lookup_mac_from_esphome_device(hass, device_id)
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

    # Register devices in registry
    # Device 1: Main physical device (for learned IR buttons and ESPHome sensors)
    # Device 2: Controls device (for learning controls, delete buttons)
    device_registry = dr.async_get(hass)

    # Main physical ESPHome device
    # Use MAC-based identifier if available for stability across ESPHome YAML changes
    device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, device_identifier)},
        name=f"OpenIRBlaster {device_id}",
        manufacturer="OpenIRBlaster",
        model="ESP8266 IR Blaster",
    )

    # Virtual controls device for learning/management
    device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, f"{device_identifier}_controls")},
        name=f"OpenIRBlaster {device_id} Controls",
        manufacturer="OpenIRBlaster",
        model="Learning & Management",
        via_device=(DOMAIN, device_identifier),  # Shows as connected through main device
    )

    # Discover ESPHome service name (with runtime discovery for resilience)
    esphome_service_name = discover_esphome_service(hass, entry)
    if not esphome_service_name:
        _LOGGER.warning(
            "ESPHome service not found during setup. IR transmission will not work "
            "until the ESPHome device is online."
        )

    # Store objects in hass.data
    hass.data.setdefault(DOMAIN, {})

    hass.data[DOMAIN][entry.entry_id] = {
        "storage": storage,
        "learning_session": learning_session,
        "config_entry": entry,
        "esphome_service_name": esphome_service_name,
    }

    # Set up platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Set up services (only once, first entry)
    if len(hass.data[DOMAIN]) == 1:
        await async_setup_services(hass)

    # Note: No update listener needed - our integration doesn't have options that require reload
    # Config entry rename is handled automatically by Home Assistant core

    _LOGGER.info("OpenIRBlaster integration setup complete for entry %s", entry.entry_id)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.info("Unloading OpenIRBlaster integration for entry %s", entry.entry_id)

    # Unload platforms
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        # Clean up learning session
        data = hass.data[DOMAIN].pop(entry.entry_id)
        learning_session: LearningSession = data["learning_session"]
        await learning_session.async_cleanup()

        # Unload services if this was the last entry
        if not hass.data[DOMAIN]:
            await async_unload_services(hass)

    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry."""
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle removal of a config entry (cleanup storage and devices)."""
    _LOGGER.info("Removing OpenIRBlaster config entry %s", entry.entry_id)

    # Delete storage file for this entry
    storage = OpenIRBlasterStorage(hass, entry.entry_id)
    await storage.async_delete()

    # Explicitly remove device registry entries for this config entry
    # (HA should do this automatically, but being explicit ensures cleanup)
    device_registry = dr.async_get(hass)
    devices_to_remove = [
        device.id
        for device in device_registry.devices.values()
        if entry.entry_id in device.config_entries
    ]
    for device_id in devices_to_remove:
        _LOGGER.debug("Removing device %s", device_id)
        device_registry.async_remove_device(device_id)

    _LOGGER.info("Cleanup complete for entry %s: storage deleted, %d devices removed",
                 entry.entry_id, len(devices_to_remove))
