"""Helper functions for OpenIRBlaster integration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

from homeassistant.core import callback
from homeassistant.helpers import entity_registry as er, issue_registry as ir

from .const import (
    CONF_ESPHOME_DEVICE_NAME,
    CONF_ESPHOME_SERVICE_NAME,
    DOMAIN,
    UNIQUE_ID_CODE_BUTTON,
)

_LOGGER = logging.getLogger(__name__)


class AmbiguousEsphomeServiceError(Exception):
    """Multiple unclaimed send_ir_raw services matched; refusing to guess.

    Raised by discover_esphome_service so setup can surface a distinct
    ConfigEntryNotReady message suggesting reconfiguration, instead of the
    generic "is the device online?" wording.
    """


@callback
def async_flag_send_service_missing(hass: HomeAssistant, entry_id: str) -> None:
    """Raise a repair: the ESPHome send service vanished after setup.

    Setup-time absence raises ConfigEntryNotReady instead; this repair
    covers the case where the service disappears later (device renamed or
    offline) and a send fails.
    """
    entry = hass.config_entries.async_get_entry(entry_id)
    ir.async_create_issue(
        hass,
        DOMAIN,
        f"esphome_service_missing_{entry_id}",
        is_fixable=False,
        severity=ir.IssueSeverity.ERROR,
        translation_key="esphome_service_missing",
        translation_placeholders={
            "name": entry.title if entry else entry_id,
        },
    )


@callback
def async_clear_send_service_missing(hass: HomeAssistant, entry_id: str) -> None:
    """Clear the missing-service repair after a successful send."""
    ir.async_delete_issue(hass, DOMAIN, f"esphome_service_missing_{entry_id}")


def async_remove_code_entities(
    hass: HomeAssistant, entry_id: str, code_id: str
) -> None:
    """Remove entity-registry entries for a deleted code's button entities.

    Without this, deleting a code leaves its button registered and the
    entity shows up as "no longer provided" after the entry reloads.
    Shared by the options-flow delete path and the delete_code service.
    """
    registry = er.async_get(hass)
    send_button_unique_id = UNIQUE_ID_CODE_BUTTON.format(
        entry_id=entry_id, code_id=code_id
    )
    delete_button_unique_id = f"{entry_id}_{code_id}_delete"

    send_button_entity_id = registry.async_get_entity_id(
        "button", DOMAIN, send_button_unique_id
    )
    delete_button_entity_id = registry.async_get_entity_id(
        "button", DOMAIN, delete_button_unique_id
    )

    candidates = {send_button_entity_id, delete_button_entity_id}
    for entity in er.async_entries_for_config_entry(registry, entry_id):
        if entity.domain != "button":
            continue
        if entity.unique_id in {send_button_unique_id, delete_button_unique_id}:
            candidates.add(entity.entity_id)

    for entity_id in candidates:
        if entity_id:
            registry.async_remove(entity_id)


def claimed_service_names(
    hass: HomeAssistant, exclude_entry_id: str | None = None
) -> set[str]:
    """Return ESPHome service names claimed by other OpenIRBlaster entries.

    Collects both the stored (config data) and cached (runtime_data) names
    so the pattern fallback never binds an entry to a service that already
    belongs to a different blaster.
    """
    claimed: set[str] = set()
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.entry_id == exclude_entry_id:
            continue
        stored = entry.data.get(CONF_ESPHOME_SERVICE_NAME)
        if stored:
            claimed.add(stored)
        data = getattr(entry, "runtime_data", None)
        cached = getattr(data, "esphome_service_name", None)
        if cached:
            claimed.add(cached)
    return claimed


def discover_esphome_service(hass: HomeAssistant, entry: ConfigEntry) -> str | None:
    """Discover the ESPHome send_ir_raw service name for a device.

    This function handles cases where:
    - The service name is stored in config entry (preferred)
    - The ESPHome device was renamed after initial setup
    - Multiple OpenIRBlaster devices exist

    Returns the service name (without 'esphome.' prefix) or None if not
    found. Raises AmbiguousEsphomeServiceError when several unclaimed
    candidates exist and none can be verified as this device's own.
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

    # Priority 3: Search for an unclaimed *_send_ir_raw service. This
    # handles ESPHome device renames, but must never grab another entry's
    # service: with two blasters and this one offline at boot, the naive
    # pattern match would bind this entry to the OTHER device and its
    # buttons would transmit from the wrong blaster. Only bind when
    # exactly one unclaimed candidate remains; otherwise return None so
    # setup raises ConfigEntryNotReady and retries.
    esphome_services = hass.services.async_services().get("esphome", {})
    claimed = claimed_service_names(hass, exclude_entry_id=entry.entry_id)
    candidates = [
        service_name
        for service_name in esphome_services
        if service_name.endswith("_send_ir_raw") and service_name not in claimed
    ]
    if len(candidates) == 1:
        _LOGGER.warning(
            "ESPHome service discovered by pattern matching: %s. "
            "Consider reconfiguring the integration if this is incorrect.",
            candidates[0],
        )
        return candidates[0]
    if len(candidates) > 1:
        _LOGGER.warning(
            "Multiple unclaimed *_send_ir_raw services found for device %s "
            "(%s); refusing to guess. Reconfigure the integration to bind "
            "the correct device.",
            device_name,
            candidates,
        )
        raise AmbiguousEsphomeServiceError(
            f"Multiple unclaimed send_ir_raw services match {device_name}: "
            f"{candidates}"
        )

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
    The service name is discovered at integration load time and stored in
    the entry's runtime_data. If users rename their ESPHome device, they
    need to reload the integration.

    Returns the service name or None if not available.
    """
    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None or entry.domain != DOMAIN:
        return None
    data = getattr(entry, "runtime_data", None)
    if data is None:
        return None
    return getattr(data, "esphome_service_name", None)
