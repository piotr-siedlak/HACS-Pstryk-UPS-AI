"""Constants for the Pstryk UPS AI Optimizer integration."""
from __future__ import annotations

DOMAIN = "pstryk_ups"
MANUFACTURER = "Pstryk UPS AI"
VERSION = "1.0.0"

# Platforms
PLATFORMS = ["sensor", "switch", "button"]

# ── Configuration keys ──────────────────────────────────────────────────────
CONF_PSTRYK_API_KEY = "pstryk_api_key"
CONF_CLAUDE_API_KEY = "claude_api_key"
CONF_UPS_MODEL = "ups_model"
CONF_BATTERY_CAPACITY = "battery_capacity_kwh"
CONF_NUM_STRINGS = "num_strings"
CONF_MAX_CHARGE_RATE = "max_charge_rate_kw"
CONF_MAX_DISCHARGE_RATE = "max_discharge_rate_kw"
CONF_BATTERY_MIN_PCT = "battery_min_pct"
CONF_BATTERY_MAX_PCT = "battery_max_pct"
CONF_MQTT_POWER_TOPIC = "mqtt_power_topic"
CONF_MQTT_HISTORY_TOPIC = "mqtt_history_topic"
CONF_MQTT_CHARGE_TOPIC = "mqtt_charge_topic"
CONF_MQTT_DISCHARGE_TOPIC = "mqtt_discharge_topic"
CONF_MQTT_BATTERY_TOPIC = "mqtt_battery_topic"
CONF_REFRESH_INTERVAL = "refresh_interval_hours"

# ── Defaults ─────────────────────────────────────────────────────────────────
DEFAULT_REFRESH_INTERVAL = 6          # hours between Pstryk API calls
DEFAULT_BATTERY_CAPACITY = 10.0       # kWh
DEFAULT_NUM_STRINGS = 1
DEFAULT_MAX_CHARGE_RATE = 2.0         # kW
DEFAULT_MAX_DISCHARGE_RATE = 2.0      # kW
DEFAULT_UPS_MODEL = "Generic UPS"
DEFAULT_BATTERY_MIN_PCT = 10.0        # never discharge below this level
DEFAULT_BATTERY_MAX_PCT = 90.0        # never charge above this level
# MQTT charge/discharge control payloads (1 = on, 0 = off)
MQTT_PAYLOAD_ON = "1"
MQTT_PAYLOAD_OFF = "0"

# ── Pstryk API ───────────────────────────────────────────────────────────────
PSTRYK_API_BASE_URL = "https://api.pstryk.pl"
# Unified metrics endpoint – the only documented pricing endpoint in the swagger.
# Query with ?metrics=pricing&resolution=hour&window_start=...&window_end=...
PSTRYK_UNIFIED_ENDPOINT = "/integrations/meter-data/unified-metrics/"
PSTRYK_API_TIMEOUT = 30               # seconds

# ── Price availability timing ─────────────────────────────────────────────────
# TGE (Polish Power Exchange) publishes next-day spot prices each afternoon.
# Before this hour (Warsaw/CET time) only current-day prices are available;
# after it we extend the fetch window to cover the full next day.
NEXT_DAY_PRICES_HOUR = 15             # 15:00 Warsaw time
WARSAW_TZ_NAME = "Europe/Warsaw"

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
SENSOR_PSTRYK_STATUS = "pstryk_api_status"
SENSOR_CLAUDE_STATUS = "claude_api_status"
BUTTON_REFRESH_PRICES = "refresh_prices"
SWITCH_CHARGING = "charging"
SWITCH_DISCHARGING = "discharging"
SWITCH_AUTO_SCHEDULE = "auto_schedule"

# ── DataUpdateCoordinator poll interval ───────────────────────────────────────
# The coordinator runs every hour; actual Pstryk API calls are rate-limited
# by CONF_REFRESH_INTERVAL (default 6 h).
UPDATE_INTERVAL_HOURS = 1

# ── Heuristic fallback config ─────────────────────────────────────────────────
HEURISTIC_CHARGE_HOURS = 8            # cheapest N hours → charge
HEURISTIC_DISCHARGE_HOURS = 4         # most expensive N hours → discharge
