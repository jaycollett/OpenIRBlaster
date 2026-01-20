"""Storage management for OpenIRBlaster integration."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import (
    ATTR_CARRIER_HZ,
    ATTR_CODE_ID,
    ATTR_CODE_NAME,
    ATTR_CREATED_AT,
    ATTR_NOTES,
    ATTR_PULSES,
    ATTR_TAGS,
    ATTR_UPDATED_AT,
    STORAGE_KEY_PREFIX,
    STORAGE_VERSION,
)

_LOGGER = logging.getLogger(__name__)


class OpenIRBlasterStorage:
    """Manage persistent storage for IR codes."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        """Initialize storage."""
        self.hass = hass
        self.entry_id = entry_id
        self._store = Store(
            hass,
            STORAGE_VERSION,
            f"{STORAGE_KEY_PREFIX}{entry_id}",
        )
        self._data: dict[str, Any] = {}

    async def async_load(self) -> dict[str, Any]:
        """Load data from storage."""
        _LOGGER.debug("Loading storage for entry %s", self.entry_id)
        data = await self._store.async_load()
        if data is None:
            _LOGGER.info("No existing storage found for entry %s, initializing empty", self.entry_id)
            # Initialize with empty structure
            self._data = {
                "version": STORAGE_VERSION,
                "device": {
                    "config_entry_id": self.entry_id,
                    "name": "OpenIRBlaster",
                    "device_id": "",
                },
                "codes": [],
            }
        else:
            self._data = data
            num_codes = len(data.get("codes", []))
            _LOGGER.info(
                "Loaded storage for entry %s: %d codes found",
                self.entry_id,
                num_codes,
            )
        return self._data

    async def async_save(self) -> None:
        """Save data to storage."""
        await self._store.async_save(self._data)

    def get_codes(self) -> list[dict[str, Any]]:
        """Get all stored IR codes."""
        return self._data.get("codes", [])

    def get_code(self, code_id: str) -> dict[str, Any] | None:
        """Get a specific code by ID."""
        for code in self._data.get("codes", []):
            if code.get(ATTR_CODE_ID) == code_id:
                return code
        return None

    def code_exists(self, code_id: str) -> bool:
        """Check if a code ID exists."""
        return self.get_code(code_id) is not None

    def name_exists(self, name: str) -> bool:
        """Check if a code name already exists (case-insensitive)."""
        name_lower = name.lower().strip()
        for code in self._data.get("codes", []):
            if code.get(ATTR_CODE_NAME, "").lower().strip() == name_lower:
                return True
        return False

    async def async_add_code(
        self,
        name: str,
        carrier_hz: int,
        pulses: list[int],
        tags: list[str] | None = None,
        notes: str = "",
    ) -> dict[str, Any]:
        """Add a new IR code to storage."""
        # Generate unique ID from name
        code_id = self._generate_unique_id(name)

        now = datetime.now(timezone.utc).isoformat()
        code = {
            ATTR_CODE_ID: code_id,
            ATTR_CODE_NAME: name,
            ATTR_CARRIER_HZ: carrier_hz,
            ATTR_PULSES: pulses,
            ATTR_CREATED_AT: now,
            ATTR_UPDATED_AT: now,
            ATTR_TAGS: tags or [],
            ATTR_NOTES: notes,
        }

        if "codes" not in self._data:
            self._data["codes"] = []
        self._data["codes"].append(code)

        await self.async_save()
        _LOGGER.info("Added code %s (%s)", name, code_id)
        return code

    async def async_update_code(
        self,
        code_id: str,
        name: str | None = None,
        carrier_hz: int | None = None,
        pulses: list[int] | None = None,
        tags: list[str] | None = None,
        notes: str | None = None,
    ) -> dict[str, Any] | None:
        """Update an existing code."""
        code = self.get_code(code_id)
        if code is None:
            _LOGGER.error("Code %s not found", code_id)
            return None

        if name is not None:
            code[ATTR_CODE_NAME] = name
        if carrier_hz is not None:
            code[ATTR_CARRIER_HZ] = carrier_hz
        if pulses is not None:
            code[ATTR_PULSES] = pulses
        if tags is not None:
            code[ATTR_TAGS] = tags
        if notes is not None:
            code[ATTR_NOTES] = notes

        code[ATTR_UPDATED_AT] = datetime.now(timezone.utc).isoformat()

        await self.async_save()
        _LOGGER.info("Updated code %s", code_id)
        return code

    async def async_delete_code(self, code_id: str) -> bool:
        """Delete a code from storage."""
        codes = self._data.get("codes", [])
        original_length = len(codes)

        self._data["codes"] = [
            code for code in codes if code.get(ATTR_CODE_ID) != code_id
        ]

        if len(self._data["codes"]) < original_length:
            await self.async_save()
            _LOGGER.info("Deleted code %s", code_id)
            return True

        _LOGGER.warning("Code %s not found for deletion", code_id)
        return False

    def _generate_unique_id(self, name: str) -> str:
        """Generate a unique slug ID from a name."""
        # Convert to lowercase, replace spaces and special chars with underscore
        slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")

        # Ensure it's not empty
        if not slug:
            slug = "code"

        # Check for collisions and append number if needed
        base_slug = slug
        counter = 2
        while self.code_exists(slug):
            slug = f"{base_slug}_{counter}"
            counter += 1

        return slug

    async def async_update_device_info(self, device_id: str, name: str | None = None) -> None:
        """Update device information in storage and save."""
        if "device" not in self._data:
            self._data["device"] = {}

        self._data["device"]["device_id"] = device_id
        if name:
            self._data["device"]["name"] = name

        await self.async_save()
