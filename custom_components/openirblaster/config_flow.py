"""Config flow for OpenIRBlaster integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import device_registry as dr, entity_registry as er, selector

from .const import (
    ATTR_CODE_ID,
    ATTR_CODE_NAME,
    CONF_DEVICE_ID,
    CONF_ESPHOME_DEVICE_NAME,
    CONF_ESPHOME_SERVICE_NAME,
    CONF_LEARNING_SWITCH_ENTITY_ID,
    DOMAIN,
    STATE_RECEIVED,
)
from .learning import LearnedCode

_LOGGER = logging.getLogger(__name__)


class OpenIRBlasterConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for OpenIRBlaster."""

    VERSION = 1

    async def _get_available_openirblaster_devices(self) -> list[dict[str, str]]:
        """Get list of available OpenIRBlaster devices not yet configured.

        Returns list of dicts with keys: 'label' (display name), 'value' (device_id)
        """
        device_registry = dr.async_get(self.hass)

        # Get existing configured device IDs
        existing_device_ids = {
            entry.unique_id for entry in self._async_current_entries()
        }

        available_devices = []
        for device in device_registry.devices.values():
            # Filter by manufacturer/model from ESPHome project name
            if device.manufacturer != "jaycollett" or device.model != "openirblaster":
                continue

            # Extract base device name from ESPHome identifiers
            base_device_name = None
            for identifier in device.identifiers:
                if identifier[0] == "esphome":
                    base_device_name = identifier[1]
                    break

            # Fallback: If no identifier found, try to get device_name from ESPHome config entry
            if not base_device_name and device.config_entries:
                for config_entry_id in device.config_entries:
                    config_entry = self.hass.config_entries.async_get_entry(config_entry_id)
                    if config_entry and config_entry.domain == "esphome":
                        base_device_name = config_entry.data.get("device_name")
                        break

            if not base_device_name:
                continue

            # With name_add_mac_suffix: true in firmware, the ESPHome device name
            # already includes the MAC suffix (e.g., "openirblaster-64c999")
            device_id = base_device_name
            _LOGGER.debug("Found device with device_id: %s", device_id)

            if not device_id or device_id in existing_device_ids:
                continue

            available_devices.append({
                "label": device.name_by_user or device.name,
                "value": device_id,
            })

        return available_devices

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors = {}

        if user_input is not None:
            device_id = user_input["device"]  # Full device_id with MAC suffix (e.g., openirblaster-293aea)

            # Find device in registry by reconstructing the device_id and matching
            device_registry = dr.async_get(self.hass)
            selected_device = None
            base_device_name = None

            # Search for OpenIRBlaster devices and match by constructed device_id
            for device in device_registry.devices.values():
                if device.manufacturer != "jaycollett" or device.model != "openirblaster":
                    continue

                # Get base name from ESPHome identifier
                base_device_name = None
                for identifier in device.identifiers:
                    if identifier[0] == "esphome":
                        base_device_name = identifier[1]
                        break

                # Fallback: get device_name from ESPHome config entry
                if not base_device_name and device.config_entries:
                    for config_entry_id in device.config_entries:
                        config_entry = self.hass.config_entries.async_get_entry(config_entry_id)
                        if config_entry and config_entry.domain == "esphome":
                            base_device_name = config_entry.data.get("device_name")
                            break

                if not base_device_name:
                    continue

                # With name_add_mac_suffix: true, ESPHome name already includes MAC suffix
                if base_device_name == device_id:
                    selected_device = device
                    break

            if not selected_device:
                errors["base"] = "device_not_found"
            else:
                # Extract base device name for ESPHome service discovery
                device_name = base_device_name or device_id.rsplit("-", 1)[0]

                # Find the learning switch entity using robust identification
                # Priority: 1) unique_id match, 2) original_name match, 3) entity_id pattern
                entity_registry = er.async_get(self.hass)
                learning_switch_entity_id = None

                # Search for the IR learning mode switch entity on this device
                # ESPHome unique_id format: {mac}-switch-{component_id}
                # Since firmware defines `id: ir_learning_mode`, unique_id ends with that
                candidates = []
                for entity in er.async_entries_for_device(entity_registry, selected_device.id):
                    if entity.domain != "switch":
                        continue

                    # Priority 1: Match by unique_id (most stable - survives renames)
                    if entity.unique_id and "ir_learning_mode" in entity.unique_id:
                        learning_switch_entity_id = entity.entity_id
                        _LOGGER.debug(
                            "Found learning switch by unique_id: %s (unique_id: %s)",
                            entity.entity_id,
                            entity.unique_id,
                        )
                        break

                    # Collect candidates for fallback matching
                    candidates.append(entity)

                # Priority 2: Match by original_name (ESPHome's defined name)
                if not learning_switch_entity_id:
                    for entity in candidates:
                        if entity.original_name == "IR Learning Mode":
                            learning_switch_entity_id = entity.entity_id
                            _LOGGER.debug(
                                "Found learning switch by original_name: %s",
                                entity.entity_id,
                            )
                            break

                # Priority 3: Match by entity_id pattern (fallback)
                if not learning_switch_entity_id:
                    for entity in candidates:
                        if entity.entity_id.endswith("_ir_learning_mode"):
                            learning_switch_entity_id = entity.entity_id
                            _LOGGER.debug(
                                "Found learning switch by entity_id pattern: %s",
                                entity.entity_id,
                            )
                            break

                # Validate learning switch was found
                if not learning_switch_entity_id:
                    errors["base"] = "entity_not_found"
                    _LOGGER.warning(
                        "Learning switch entity not found for device: %s (device_id: %s). "
                        "Searched %d switch entities on device.",
                        selected_device.name,
                        device_id,
                        len(candidates),
                    )

                if not errors:
                    # Discover the ESPHome send_ir_raw service name
                    # ESPHome registers services as esphome.{device_name}_send_ir_raw
                    esphome_service_name = None
                    esphome_services = self.hass.services.async_services().get("esphome", {})

                    # Try exact match first (device_name with hyphens converted to underscores)
                    normalized_name = device_name.replace("-", "_")
                    expected_service = f"{normalized_name}_send_ir_raw"
                    if expected_service in esphome_services:
                        esphome_service_name = expected_service
                        _LOGGER.debug(
                            "Found ESPHome service by exact match: %s",
                            esphome_service_name,
                        )

                    # If not found, search for any *_send_ir_raw service
                    # This handles cases where device naming differs
                    if not esphome_service_name:
                        for service_name in esphome_services:
                            if service_name.endswith("_send_ir_raw"):
                                # Found a potential match - use it if it's the only one
                                # or if it somewhat matches our device name
                                if esphome_service_name is None:
                                    esphome_service_name = service_name
                                    _LOGGER.debug(
                                        "Found ESPHome service by pattern: %s",
                                        esphome_service_name,
                                    )

                    if not esphome_service_name:
                        errors["base"] = "service_not_found"
                        _LOGGER.warning(
                            "ESPHome send_ir_raw service not found for device: %s. "
                            "Available esphome services: %s",
                            device_name,
                            list(esphome_services.keys()),
                        )

                if not errors:
                    await self.async_set_unique_id(device_id)
                    self._abort_if_unique_id_configured()

                    return self.async_create_entry(
                        title=f"OpenIRBlaster {device_name}",
                        data={
                            CONF_ESPHOME_DEVICE_NAME: device_name,
                            CONF_DEVICE_ID: device_id,
                            CONF_LEARNING_SWITCH_ENTITY_ID: learning_switch_entity_id,
                            CONF_ESPHOME_SERVICE_NAME: esphome_service_name,
                        },
                    )

        # Get available devices
        available_devices = await self._get_available_openirblaster_devices()

        if not available_devices:
            return self.async_abort(reason="no_devices_found")

        # Build schema with SelectSelector
        data_schema = vol.Schema({
            vol.Required("device"): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=available_devices,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            )
        })

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> OpenIRBlasterOptionsFlow:
        """Get the options flow for this handler."""
        return OpenIRBlasterOptionsFlow(config_entry)


class OpenIRBlasterOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow for OpenIRBlaster."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        super().__init__()
        self._config_entry = config_entry
        self._selected_code_id: str | None = None
        self._selected_code_name: str | None = None

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        # Check if there's a pending learned code
        entry_id = self.config_entry.entry_id
        if DOMAIN not in self.hass.data or entry_id not in self.hass.data[DOMAIN]:
            return self.async_abort(reason="not_loaded")

        learning_session = self.hass.data[DOMAIN][entry_id]["learning_session"]

        if learning_session.state == STATE_RECEIVED and learning_session.pending_code:
            return await self.async_step_save_code(user_input)

        # Show options menu
        return self.async_show_menu(
            step_id="init",
            menu_options=["manage_codes", "settings"],
        )

    async def async_step_save_code(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Save a pending learned code."""
        entry_id = self.config_entry.entry_id
        storage = self.hass.data[DOMAIN][entry_id]["storage"]
        learning_session = self.hass.data[DOMAIN][entry_id]["learning_session"]

        pending_code: LearnedCode = learning_session.pending_code

        if user_input is not None:
            name = user_input[CONF_NAME]
            tags = user_input.get("tags", "").split(",")
            tags = [tag.strip() for tag in tags if tag.strip()]
            notes = user_input.get("notes", "")

            # Save code to storage
            await storage.async_add_code(
                name=name,
                carrier_hz=pending_code.carrier_hz,
                pulses=pending_code.pulses,
                tags=tags,
                notes=notes,
            )

            # Clear pending code
            learning_session.clear_pending()

            # Reload entry to create new button entity
            self.hass.async_create_task(
                self.hass.config_entries.async_reload(entry_id)
            )

            return self.async_create_entry(title="", data={})

        # Show form to name the code
        data_schema = vol.Schema(
            {
                vol.Required(CONF_NAME): str,
                vol.Optional("tags"): str,
                vol.Optional("notes"): str,
            }
        )

        return self.async_show_form(
            step_id="save_code",
            data_schema=data_schema,
            description_placeholders={
                "carrier_hz": str(pending_code.carrier_hz),
                "pulse_count": str(len(pending_code.pulses)),
                "timestamp": pending_code.timestamp,
            },
        )

    async def async_step_manage_codes(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage stored codes."""
        entry_id = self.config_entry.entry_id
        storage = self.hass.data[DOMAIN][entry_id]["storage"]

        codes = storage.get_codes()
        if not codes:
            return self.async_abort(reason="no_codes")

        if user_input is not None:
            code_id = user_input["code"]
            code_name = None
            for code in codes:
                if code.get(ATTR_CODE_ID) == code_id:
                    code_name = code.get(ATTR_CODE_NAME)
                    break

            self._selected_code_id = code_id
            self._selected_code_name = code_name or code_id
            return await self.async_step_confirm_delete()

        options = [
            {
                "label": f"{code.get(ATTR_CODE_NAME)} ({code.get(ATTR_CODE_ID)})",
                "value": code.get(ATTR_CODE_ID),
            }
            for code in codes
        ]

        data_schema = vol.Schema(
            {
                vol.Required("code"): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=options,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                )
            }
        )

        return self.async_show_form(
            step_id="manage_codes",
            data_schema=data_schema,
        )

    async def async_step_confirm_delete(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Confirm deletion of a selected code."""
        errors: dict[str, str] = {}
        entry_id = self.config_entry.entry_id
        storage = self.hass.data[DOMAIN][entry_id]["storage"]

        if not self._selected_code_id:
            return await self.async_step_manage_codes()

        if user_input is not None:
            if not user_input.get("confirm", False):
                return await self.async_step_init()

            success = await storage.async_delete_code(self._selected_code_id)
            if not success:
                errors["base"] = "code_not_found"
            else:
                await self.hass.config_entries.async_reload(entry_id)
                return self.async_create_entry(title="", data={})

        data_schema = vol.Schema(
            {
                vol.Required("confirm", default=False): bool,
            }
        )

        return self.async_show_form(
            step_id="confirm_delete",
            data_schema=data_schema,
            errors=errors,
            description_placeholders={
                "code_name": self._selected_code_name or self._selected_code_id,
            },
        )

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage integration settings."""
        # Placeholder for future settings UI
        return self.async_abort(reason="not_implemented")
