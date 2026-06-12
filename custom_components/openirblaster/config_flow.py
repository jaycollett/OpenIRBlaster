"""Config flow for OpenIRBlaster integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState, ConfigFlowResult
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers import device_registry as dr, entity_registry as er, selector

from .const import (
    ATTR_CODE_ID,
    ATTR_CODE_NAME,
    CONF_DEVICE_ID,
    CONF_ESPHOME_DEVICE_NAME,
    CONF_ESPHOME_SERVICE_NAME,
    CONF_LEARNING_SWITCH_ENTITY_ID,
    CONF_MAC_ADDRESS,
    DOMAIN,
    STATE_RECEIVED,
)
from .helpers import async_remove_code_entities
from .learning import LearnedCode

_LOGGER = logging.getLogger(__name__)


class OpenIRBlasterConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for OpenIRBlaster."""

    VERSION = 1

    async def _get_available_openirblaster_devices(
        self, exclude_entry_id: str | None = None
    ) -> list[dict[str, Any]]:
        """Get list of available OpenIRBlaster devices not yet configured.

        Returns list of dicts with keys:
          - 'label': display name
          - 'value': device_id (for dropdown selection)
          - 'mac_address': MAC address if available (for unique_id)
          - 'ha_device': the HA device registry entry

        Args:
            exclude_entry_id: When set (reconfigure flow), this entry's own
                unique_id does not count as "already configured", so the
                entry's current (possibly renamed) device stays selectable.
        """
        device_registry = dr.async_get(self.hass)
        entity_registry = er.async_get(self.hass)

        # Get existing configured unique_ids (could be device_id or MAC-based)
        existing_unique_ids = {
            entry.unique_id
            for entry in self._async_current_entries()
            if entry.entry_id != exclude_entry_id
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

            # Try to get MAC address from the device's MAC Address sensor
            # Note: ESPHome wifi_info mac_address appears as "sensor" domain in HA
            mac_address = None
            for entity in er.async_entries_for_device(entity_registry, device.id):
                # ESPHome wifi_info mac_address sensor has unique_id ending with mac_address
                # and original_name "MAC Address"
                if entity.domain in ("sensor", "text_sensor"):
                    if (
                        entity.unique_id and "mac_address" in entity.unique_id.lower()
                    ) or entity.original_name == "MAC Address":
                        # Get the sensor state
                        state = self.hass.states.get(entity.entity_id)
                        if state and state.state not in ("unknown", "unavailable", None, ""):
                            mac_address = state.state
                            _LOGGER.debug(
                                "Found MAC address %s for device %s (entity: %s)",
                                mac_address,
                                device_id,
                                entity.entity_id,
                            )
                        break

            # Determine unique_id for duplicate checking
            # Prefer MAC-based unique_id if available, fall back to device_id
            if mac_address:
                normalized_mac = mac_address.lower().replace(":", "")
                unique_id_candidate = normalized_mac
            else:
                unique_id_candidate = device_id

            # Skip if already configured (check both MAC-based and device_id-based)
            if unique_id_candidate in existing_unique_ids or device_id in existing_unique_ids:
                continue

            available_devices.append({
                "label": device.name_by_user or device.name,
                "value": device_id,
                "mac_address": mac_address,
                "ha_device": device,
            })

        return available_devices

    def _find_selected_device_info(
        self, device_id: str, available_devices: list[dict[str, Any]]
    ) -> dict[str, Any] | None:
        """Locate the selected device info, with a registry fallback search."""
        for dev_info in available_devices:
            if dev_info["value"] == device_id:
                return dev_info

        # Fallback: search device registry directly
        device_registry = dr.async_get(self.hass)
        for device in device_registry.devices.values():
            if device.manufacturer != "jaycollett" or device.model != "openirblaster":
                continue

            base_device_name = None
            for identifier in device.identifiers:
                if identifier[0] == "esphome":
                    base_device_name = identifier[1]
                    break

            if not base_device_name and device.config_entries:
                for config_entry_id in device.config_entries:
                    config_entry = self.hass.config_entries.async_get_entry(config_entry_id)
                    if config_entry and config_entry.domain == "esphome":
                        base_device_name = config_entry.data.get("device_name")
                        break

            if base_device_name == device_id:
                return {
                    "value": device_id,
                    "mac_address": None,
                    "ha_device": device,
                }

        return None

    def _resolve_learning_switch(self, selected_device: dr.DeviceEntry) -> str | None:
        """Find the learning switch entity using robust identification.

        Priority: 1) unique_id match, 2) original_name match,
        3) entity_id pattern.
        """
        entity_registry = er.async_get(self.hass)

        # Search for the IR learning mode switch entity on this device
        # ESPHome unique_id format: {mac}-switch-{component_id}
        # Since firmware defines `id: ir_learning_mode`, unique_id ends with that
        candidates = []
        for entity in er.async_entries_for_device(entity_registry, selected_device.id):
            if entity.domain != "switch":
                continue

            # Priority 1: Match by unique_id (most stable - survives renames)
            if entity.unique_id and "ir_learning_mode" in entity.unique_id:
                _LOGGER.debug(
                    "Found learning switch by unique_id: %s (unique_id: %s)",
                    entity.entity_id,
                    entity.unique_id,
                )
                return entity.entity_id

            # Collect candidates for fallback matching
            candidates.append(entity)

        # Priority 2: Match by original_name (ESPHome's defined name)
        for entity in candidates:
            if entity.original_name == "IR Learning Mode":
                _LOGGER.debug(
                    "Found learning switch by original_name: %s",
                    entity.entity_id,
                )
                return entity.entity_id

        # Priority 3: Match by entity_id pattern (fallback)
        for entity in candidates:
            if entity.entity_id.endswith("_ir_learning_mode"):
                _LOGGER.debug(
                    "Found learning switch by entity_id pattern: %s",
                    entity.entity_id,
                )
                return entity.entity_id

        _LOGGER.warning(
            "Learning switch entity not found for device: %s. "
            "Searched %d switch entities on device.",
            selected_device.name,
            len(candidates),
        )
        return None

    def _resolve_esphome_service(self, device_name: str) -> str | None:
        """Discover the ESPHome send_ir_raw service name for a device.

        ESPHome registers services as esphome.{device_name}_send_ir_raw.
        """
        esphome_services = self.hass.services.async_services().get("esphome", {})

        # Try exact match first (device_name with hyphens converted to underscores)
        normalized_name = device_name.replace("-", "_")
        expected_service = f"{normalized_name}_send_ir_raw"
        if expected_service in esphome_services:
            _LOGGER.debug(
                "Found ESPHome service by exact match: %s", expected_service
            )
            return expected_service

        # If not found, search for any *_send_ir_raw service
        # This handles cases where device naming differs
        for service_name in esphome_services:
            if service_name.endswith("_send_ir_raw"):
                _LOGGER.debug(
                    "Found ESPHome service by pattern: %s", service_name
                )
                return service_name

        _LOGGER.warning(
            "ESPHome send_ir_raw service not found for device: %s. "
            "Available esphome services: %s",
            device_name,
            list(esphome_services.keys()),
        )
        return None

    @staticmethod
    def _device_selection_schema(
        available_devices: list[dict[str, Any]],
    ) -> vol.Schema:
        """Build the device-selection dropdown schema."""
        dropdown_options = [
            {"label": dev["label"], "value": dev["value"]}
            for dev in available_devices
        ]
        return vol.Schema({
            vol.Required("device"): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=dropdown_options,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            )
        })

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        # Get available devices (needed for both display and processing)
        available_devices = await self._get_available_openirblaster_devices()

        if user_input is not None:
            device_id = user_input["device"]  # Full device_id with MAC suffix (e.g., openirblaster-293aea)

            selected_device_info = self._find_selected_device_info(
                device_id, available_devices
            )

            if not selected_device_info:
                errors["base"] = "device_not_found"
            else:
                selected_device = selected_device_info["ha_device"]
                mac_address = selected_device_info.get("mac_address")

                # Extract base device name for ESPHome service discovery
                device_name = device_id

                learning_switch_entity_id = self._resolve_learning_switch(
                    selected_device
                )
                if not learning_switch_entity_id:
                    errors["base"] = "entity_not_found"

                if not errors:
                    esphome_service_name = self._resolve_esphome_service(device_name)
                    if not esphome_service_name:
                        errors["base"] = "service_not_found"

                if not errors:
                    # Determine unique_id: prefer MAC address (stable), fall back to device_id
                    if mac_address:
                        # Normalize MAC: lowercase, no colons (e.g., "aabbccddeeff")
                        normalized_mac = mac_address.lower().replace(":", "")
                        unique_id = normalized_mac
                        _LOGGER.info(
                            "Using MAC-based unique_id %s for device %s",
                            unique_id,
                            device_id,
                        )
                    else:
                        unique_id = device_id
                        _LOGGER.info(
                            "MAC address not available, using device_id as unique_id: %s",
                            unique_id,
                        )

                    await self.async_set_unique_id(unique_id)
                    self._abort_if_unique_id_configured()

                    # Build config entry data
                    entry_data = {
                        CONF_ESPHOME_DEVICE_NAME: device_name,
                        CONF_DEVICE_ID: device_id,
                        CONF_LEARNING_SWITCH_ENTITY_ID: learning_switch_entity_id,
                        CONF_ESPHOME_SERVICE_NAME: esphome_service_name,
                    }

                    # Store MAC address if available (for event filtering and device registry)
                    if mac_address:
                        entry_data[CONF_MAC_ADDRESS] = mac_address

                    return self.async_create_entry(
                        title=f"OpenIRBlaster {device_name}",
                        data=entry_data,
                    )

        if not available_devices:
            return self.async_abort(reason="no_devices_found")

        return self.async_show_form(
            step_id="user",
            data_schema=self._device_selection_schema(available_devices),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Re-bind the entry to its (possibly renamed) ESPHome device.

        Lets users recover from an ESPHome device rename without removing
        and re-adding the integration. The entry's own device stays
        selectable; picking different hardware (a different MAC-based
        unique id) aborts with wrong_device unless the original entry has
        no MAC stored, in which case the MAC is back-filled.
        """
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        available_devices = await self._get_available_openirblaster_devices(
            exclude_entry_id=entry.entry_id
        )

        if user_input is not None:
            device_id = user_input["device"]

            selected_device_info = self._find_selected_device_info(
                device_id, available_devices
            )

            if not selected_device_info:
                errors["base"] = "device_not_found"
            else:
                selected_device = selected_device_info["ha_device"]
                mac_address = selected_device_info.get("mac_address")

                # Guard the entry's hardware identity: when the original
                # entry knows its MAC, the selected device must be the same
                # hardware. Rebinding to different hardware silently would
                # orphan the stored code library's provenance.
                if entry.data.get(CONF_MAC_ADDRESS):
                    if mac_address:
                        candidate_unique_id = mac_address.lower().replace(":", "")
                    else:
                        candidate_unique_id = device_id
                    if candidate_unique_id != entry.unique_id:
                        return self.async_abort(reason="wrong_device")

                learning_switch_entity_id = self._resolve_learning_switch(
                    selected_device
                )
                if not learning_switch_entity_id:
                    errors["base"] = "entity_not_found"

                if not errors:
                    esphome_service_name = self._resolve_esphome_service(device_id)
                    if not esphome_service_name:
                        errors["base"] = "service_not_found"

                if not errors:
                    data_updates = {
                        CONF_ESPHOME_DEVICE_NAME: device_id,
                        CONF_DEVICE_ID: device_id,
                        CONF_LEARNING_SWITCH_ENTITY_ID: learning_switch_entity_id,
                        CONF_ESPHOME_SERVICE_NAME: esphome_service_name,
                    }
                    # Back-fill the MAC when available (the wrong-device
                    # guard above already ensured it matches when the entry
                    # had one stored).
                    if mac_address:
                        data_updates[CONF_MAC_ADDRESS] = mac_address

                    return self.async_update_reload_and_abort(
                        entry, data_updates=data_updates
                    )

        if not available_devices:
            return self.async_abort(reason="no_devices_found")

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self._device_selection_schema(available_devices),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> OpenIRBlasterOptionsFlow:
        """Get the options flow for this handler."""
        return OpenIRBlasterOptionsFlow()


class OpenIRBlasterOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow for OpenIRBlaster."""

    _selected_code_id: str | None = None
    _selected_code_name: str | None = None

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if self.config_entry.state is not ConfigEntryState.LOADED:
            return self.async_abort(reason="not_loaded")

        learning_session = self.config_entry.runtime_data.learning_session

        if learning_session.state == STATE_RECEIVED and learning_session.pending_code:
            return await self.async_step_save_code(user_input)

        # Show options menu
        return self.async_show_menu(
            step_id="init",
            menu_options=["manage_codes", "settings"],
        )

    async def async_step_save_code(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Save a pending learned code."""
        entry_id = self.config_entry.entry_id
        data = self.config_entry.runtime_data
        storage = data.storage
        learning_session = data.learning_session

        pending_code: LearnedCode | None = learning_session.pending_code

        # The pending code can disappear while the form is open (auto-save
        # completed, session timed out, or a racing save cleared it).
        # Without this guard the attribute access below raises and the user
        # sees "Unknown error occurred".
        if pending_code is None:
            return self.async_abort(reason="no_pending_code")

        errors: dict[str, str] = {}

        if user_input is not None:
            name = user_input[CONF_NAME]

            if storage.name_exists(name):
                errors["name"] = "name_exists"
            else:
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

                # Persist last-learned metadata so the sensors survive the
                # reload below and HA restarts.
                await storage.async_set_last_learned(
                    name=name,
                    timestamp=pending_code.timestamp,
                    pulse_count=len(pending_code.pulses),
                )
                data.last_learned_name = name
                data.last_learned_timestamp = pending_code.timestamp
                data.last_learned_pulse_count = len(pending_code.pulses)

                # Clear pending code before scheduling the reload so the
                # session teardown does not race the reload's cleanup.
                await learning_session.async_clear_pending()

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
            errors=errors,
            description_placeholders={
                "carrier_hz": str(pending_code.carrier_hz),
                "pulse_count": str(len(pending_code.pulses)),
                "timestamp": pending_code.timestamp,
            },
        )

    async def async_step_manage_codes(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage stored codes."""
        storage = self.config_entry.runtime_data.storage

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
    ) -> ConfigFlowResult:
        """Confirm deletion of a selected code."""
        errors: dict[str, str] = {}
        entry_id = self.config_entry.entry_id
        storage = self.config_entry.runtime_data.storage

        if not self._selected_code_id:
            return await self.async_step_manage_codes()

        if user_input is not None:
            if not user_input.get("confirm", False):
                return await self.async_step_init()

            success = await storage.async_delete_code(self._selected_code_id)
            if not success:
                errors["base"] = "code_not_found"
            else:
                async_remove_code_entities(
                    self.hass, entry_id, self._selected_code_id
                )
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
    ) -> ConfigFlowResult:
        """Manage integration settings."""
        # Placeholder for future settings UI
        return self.async_abort(reason="not_implemented")
