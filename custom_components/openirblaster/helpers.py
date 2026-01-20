"""Helper functions for OpenIRBlaster integration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

from .const import (
    CONF_ESPHOME_DEVICE_NAME,
    CONF_ESPHOME_SERVICE_NAME,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


def discover_esphome_service(hass: HomeAssistant, entry: ConfigEntry) -> str | None:
    """Discover the ESPHome send_ir_raw service name for a device.

    This function handles cases where:
    - The service name is stored in config entry (preferred)
    - The ESPHome device was renamed after initial setup
    - Multiple OpenIRBlaster devices exist

    Returns the service name (without 'esphome.' prefix) or None if not found.
    """
    # Priority 1: Try stored service name from config entry
    stored_service = entry.data.get(CONF_ESPHOME_SERVICE_NAME)
    if stored_service:
        esphome_services = hass.services.async_services().get("esphome", {})
        if stored_service in esphome_services:
            _LOGGER.debug("Using stored ESPHome service: %s", stored_service)
            return stored_service
        _LOGGER.debug("Stored service %s not found, attempting discovery", stored_service)

    # Priority 2: Construct from device name (with normalization)
    device_name = entry.data.get(CONF_ESPHOME_DEVICE_NAME)
    if device_name:
        normalized_name = device_name.replace("-", "_")
        expected_service = f"{normalized_name}_send_ir_raw"
        esphome_services = hass.services.async_services().get("esphome", {})
        if expected_service in esphome_services:
            _LOGGER.debug("Found ESPHome service by device name: %s", expected_service)
            return expected_service

    # Priority 3: Search for any *_send_ir_raw service
    # This handles cases where ESPHome device was renamed
    esphome_services = hass.services.async_services().get("esphome", {})
    for service_name in esphome_services:
        if service_name.endswith("_send_ir_raw"):
            _LOGGER.warning(
                "ESPHome service discovered by pattern matching: %s. "
                "Consider reconfiguring the integration if this is incorrect.",
                service_name,
            )
            return service_name

    _LOGGER.error(
        "No ESPHome send_ir_raw service found for device %s. "
        "Available services: %s",
        device_name,
        list(esphome_services.keys()),
    )
    return None


def get_esphome_service(hass: HomeAssistant, entry_id: str) -> str | None:
    """Get the cached ESPHome service name for an entry.

    This is the primary function that button.py and services.py should use.
    The service name is discovered at integration load time.
    If users rename their ESPHome device, they need to reload the integration.

    Returns the service name or None if not available.
    """
    if DOMAIN not in hass.data or entry_id not in hass.data[DOMAIN]:
        return None
    return hass.data[DOMAIN][entry_id].get("esphome_service_name")
