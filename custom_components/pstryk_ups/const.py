"""Constants for the Pstryk UPS AI Optimizer integration."""
from __future__ import annotations

DOMAIN = "pstryk_ups"
MANUFACTURER = "Pstryk UPS AI"
VERSION = "1.0.0"

# Platforms
PLATFORMS = ["sensor", "switch"]

# ── Configuration keys ──────────────────────────────────────────────────────
CONF_PSTRYK_API_KEY = "pstryk_api_key"
CONF_CLAUDE_API_KEY = "claude_api_key"
CONF_UPS_MODEL = "ups_model"
CONF_BATTERY_CAPACITY = "battery_capacity_kwh"
CONF_NUM_STRINGS = "num_strings"
CONF_MAX_CHARGE_RATE = "max_charge_rate_kw"
CONF_MAX_DISCHARGE_RATE = "max_discharge_rate_kw"
CONF_MQTT_POWER_TOPIC = "mqtt_power_topic"
CONF_MQTT_HISTORY_TOPIC = "mqtt_history_topic"
CONF_MQTT_CONTROL_TOPIC = "mqtt_control_topic"
CONF_MQTT_BATTERY_TOPIC = "mqtt_battery_topic"
CONF_REFRESH_INTERVAL = "refresh_interval_hours"

# ── Defaults ─────────────────────────────────────────────────────────────────
DEFAULT_REFRESH_INTERVAL = 6          # hours between Pstryk API calls
DEFAULT_BATTERY_CAPACITY = 10.0       # kWh
DEFAULT_NUM_STRINGS = 1
DEFAULT_MAX_CHARGE_RATE = 2.0         # kW
DEFAULT_MAX_DISCHARGE_RATE = 2.0      # kW
DEFAULT_UPS_MODEL = "Generic UPS"
DEFAULT_MQTT_CONTROL_PAYLOAD_ON = "ON"
DEFAULT_MQTT_CONTROL_PAYLOAD_OFF = "OFF"

# ── Pstryk API ───────────────────────────────────────────────────────────────
PSTRYK_API_BASE_URL = "https://api.pstryk.pl"
PSTRYK_PRICING_ENDPOINT = "/integrations/pricing/"
PSTRYK_API_TIMEOUT = 30               # seconds

# ── Claude AI ────────────────────────────────────────────────────────────────
CLAUDE_MODEL = "claude-opus-4-6"
CLAUDE_MAX_TOKENS = 4096
CLAUDE_TEMPERATURE = 0                # deterministic scheduling decisions

# ── Internal data-store keys ─────────────────────────────────────────────────
DATA_COORDINATOR = "coordinator"
DATA_MQTT_UNSUB = "mqtt_unsub"

# ── Schedule actions ──────────────────────────────────────────────────────────
ACTION_CHARGE = "charge"
ACTION_DISCHARGE = "discharge"
ACTION_IDLE = "idle"

# ── Entity unique-ID suffixes ─────────────────────────────────────────────────
SENSOR_CURRENT_PRICE = "current_price"
SENSOR_CURRENT_POWER = "current_power"
SENSOR_SCHEDULE_STATUS = "schedule_status"
SENSOR_NEXT_CHARGE = "next_charge_window"
SENSOR_NEXT_DISCHARGE = "next_discharge_window"
SENSOR_BATTERY_LEVEL = "battery_level"
SENSOR_DAILY_SAVINGS = "daily_savings"
SWITCH_CHARGING = "charging"
SWITCH_AUTO_SCHEDULE = "auto_schedule"

# ── DataUpdateCoordinator poll interval ───────────────────────────────────────
# The coordinator runs every hour; actual Pstryk API calls are rate-limited
# by CONF_REFRESH_INTERVAL (default 6 h).
UPDATE_INTERVAL_HOURS = 1

# ── Heuristic fallback config ─────────────────────────────────────────────────
HEURISTIC_CHARGE_HOURS = 8            # cheapest N hours → charge
HEURISTIC_DISCHARGE_HOURS = 4         # most expensive N hours → discharge
MIN_BATTERY_RESERVE_PCT = 10.0        # never discharge below this level
