"""Constants for the OpenIRBlaster integration."""

DOMAIN = "openirblaster"

# Config entry data keys
CONF_LEARNING_SWITCH_ENTITY_ID = "learning_switch_entity_id"
CONF_DEVICE_ID = "device_id"
CONF_ESPHOME_DEVICE_NAME = "esphome_device_name"

# Default entity patterns
DEFAULT_LEARNING_SWITCH_PATTERN = "switch.{device}_ir_learning_mode"
DEFAULT_SERVICE_NAME_PATTERN = "esphome.{device}_send_ir_raw"

# Event types
# Note: ESPHome fires this event name (see hardware_config/factory_config.yaml line 136)
EVENT_LEARNED = "esphome.openirblaster_learned"

# Learning session
LEARNING_TIMEOUT_SECONDS = 30
MAX_PULSE_ARRAY_LENGTH = 2000

# Learning states
STATE_IDLE = "idle"
STATE_ARMED = "armed"
STATE_RECEIVED = "received"
STATE_SAVED = "saved"
STATE_CANCELLED = "cancelled"
STATE_TIMEOUT = "timeout"

# Storage
STORAGE_VERSION = 1
STORAGE_KEY_PREFIX = "openirblaster_"

# Services
SERVICE_LEARN_START = "learn_start"
SERVICE_SEND_CODE = "send_code"
SERVICE_DELETE_CODE = "delete_code"
SERVICE_RENAME_CODE = "rename_code"
SERVICE_SAVE_PENDING = "save_pending"

# Attributes for learned event payload
ATTR_DEVICE_ID = "device_id"
ATTR_CARRIER_HZ = "carrier_hz"
ATTR_PULSES = "pulses"
ATTR_PULSES_JSON = "pulses_json"  # Firmware sends JSON string, not array
ATTR_TIMESTAMP = "timestamp"
ATTR_RSSI = "rssi"

# Code storage attributes
ATTR_CODE_ID = "id"
ATTR_CODE_NAME = "name"
ATTR_CREATED_AT = "created_at"
ATTR_UPDATED_AT = "updated_at"
ATTR_TAGS = "tags"
ATTR_NOTES = "notes"

# Entity unique ID patterns
UNIQUE_ID_LEARN_BUTTON = "{entry_id}_learn"
UNIQUE_ID_SEND_LAST_BUTTON = "{entry_id}_send_last"
UNIQUE_ID_CODE_BUTTON = "{entry_id}_{code_id}"
UNIQUE_ID_CODE_NAME_INPUT = "{entry_id}_code_name_input"
UNIQUE_ID_LAST_LEARNED_NAME = "{entry_id}_last_learned_name"
UNIQUE_ID_LAST_LEARNED_AT = "{entry_id}_last_learned_at"
UNIQUE_ID_LAST_LEARNED_LEN = "{entry_id}_last_learned_len"
