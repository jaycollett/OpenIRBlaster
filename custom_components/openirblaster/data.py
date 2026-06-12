"""Runtime data structures for the OpenIRBlaster integration."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry

from .learning import LearningSession
from .storage import OpenIRBlasterStorage


@dataclass
class OpenIRBlasterData:
    """Runtime data stored on the config entry while it is loaded.

    The last_learned_* fields mirror the persisted values in storage
    (see OpenIRBlasterStorage.async_set_last_learned); storage is the
    source of truth that survives reloads and restarts.
    """

    storage: OpenIRBlasterStorage
    learning_session: LearningSession
    esphome_service_name: str | None
    last_learned_name: str | None = None
    last_learned_timestamp: str | None = None
    last_learned_pulse_count: int | None = None


type OpenIRBlasterConfigEntry = ConfigEntry[OpenIRBlasterData]
