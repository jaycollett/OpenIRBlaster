"""Mock ESPHome integration for testing."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

DOMAIN = "esphome"


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the mock ESPHome integration."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up mock ESPHome from a config entry."""
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a mock ESPHome config entry."""
    return True
