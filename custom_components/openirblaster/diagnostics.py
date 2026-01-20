"""Diagnostics support for OpenIRBlaster."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    ATTR_CARRIER_HZ,
    ATTR_CREATED_AT,
    ATTR_PULSES,
    ATTR_TAGS,
    ATTR_UPDATED_AT,
    CONF_DEVICE_ID,
    CONF_ESPHOME_DEVICE_NAME,
    CONF_ESPHOME_SERVICE_NAME,
    CONF_LEARNING_SWITCH_ENTITY_ID,
    DOMAIN,
)
from .storage import OpenIRBlasterStorage

TO_REDACT = {
    "device_id",
    "config_entry_id",
    CONF_DEVICE_ID,
    CONF_LEARNING_SWITCH_ENTITY_ID,
    CONF_ESPHOME_DEVICE_NAME,
    CONF_ESPHOME_SERVICE_NAME,
    ATTR_PULSES,
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    data = hass.data.get(DOMAIN, {}).get(config_entry.entry_id, {})
    storage: OpenIRBlasterStorage | None = data.get("storage")

    storage_device = None
    codes_summary: list[dict[str, Any]] = []
    storage_version = None

    if storage is not None:
        storage_device = storage._data.get("device")  # noqa: SLF001 - diagnostics needs internal snapshot
        storage_version = storage._data.get("version")  # noqa: SLF001 - diagnostics needs internal snapshot

        for code in storage.get_codes():
            tags = code.get(ATTR_TAGS) or []
            pulses = code.get(ATTR_PULSES) or []
            codes_summary.append(
                {
                    ATTR_CARRIER_HZ: code.get(ATTR_CARRIER_HZ),
                    "pulse_count": len(pulses),
                    "tags_count": len(tags),
                    ATTR_CREATED_AT: code.get(ATTR_CREATED_AT),
                    ATTR_UPDATED_AT: code.get(ATTR_UPDATED_AT),
                }
            )

    diagnostics: dict[str, Any] = {
        "entry": {
            "title": config_entry.title,
            "data": dict(config_entry.data),
            "options": dict(config_entry.options),
        },
        "runtime": {
            "esphome_service_name": data.get("esphome_service_name"),
            "learning_state": getattr(data.get("learning_session"), "state", None),
            "has_pending_code": bool(
                getattr(data.get("learning_session"), "pending_code", None)
            ),
        },
        "storage": {
            "version": storage_version,
            "device": storage_device,
            "codes_count": len(codes_summary),
            "codes_summary": codes_summary,
        },
    }

    return async_redact_data(diagnostics, TO_REDACT)
