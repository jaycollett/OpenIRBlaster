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
    DOMAIN,
)
from .helpers import discover_esphome_service
from .learning import LearningSession
from .services import async_setup_services, async_unload_services
from .storage import OpenIRBlasterStorage

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.BUTTON, Platform.SENSOR, Platform.TEXT]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up OpenIRBlaster from a config entry."""
    _LOGGER.info("Setting up OpenIRBlaster integration for entry %s", entry.entry_id)

    device_id = entry.data[CONF_DEVICE_ID]

    # Initialize storage
    storage = OpenIRBlasterStorage(hass, entry.entry_id)
    await storage.async_load()

    # Update device info in storage
    await storage.async_update_device_info(device_id)

    # Initialize learning session
    learning_session = LearningSession(
        hass,
        entry.entry_id,
        device_id,
        entry.data[CONF_LEARNING_SWITCH_ENTITY_ID],
    )

    # Register devices in registry
    # Device 1: Main physical device (for learned IR buttons and ESPHome sensors)
    # Device 2: Controls device (for learning controls, delete buttons)
    device_registry = dr.async_get(hass)

    # Main physical ESPHome device
    device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, device_id)},
        name=f"OpenIRBlaster {device_id}",
        manufacturer="OpenIRBlaster",
        model="ESP8266 IR Blaster",
    )

    # Virtual controls device for learning/management
    device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, f"{device_id}_controls")},
        name=f"OpenIRBlaster {device_id} Controls",
        manufacturer="OpenIRBlaster",
        model="Learning & Management",
        via_device=(DOMAIN, device_id),  # Shows as connected through main device
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
