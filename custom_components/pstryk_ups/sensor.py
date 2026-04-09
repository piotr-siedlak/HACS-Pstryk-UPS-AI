"""Sensor platform for the Pstryk UPS AI Optimizer integration."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    UnitOfEnergy,
    UnitOfPower,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_UPS_MODEL,
    DATA_COORDINATOR,
    DEFAULT_UPS_MODEL,
    DOMAIN,
    MANUFACTURER,
    SENSOR_BATTERY_LEVEL,
    SENSOR_CLAUDE_STATUS,
    SENSOR_CURRENT_POWER,
    SENSOR_CURRENT_PRICE,
    SENSOR_DAILY_SAVINGS,
    SENSOR_NEXT_CHARGE,
    SENSOR_NEXT_DISCHARGE,
    SENSOR_PSTRYK_STATUS,
    SENSOR_SCHEDULE_STATUS,
    VERSION,
)
from .coordinator import PstrykUPSCoordinator

_LOGGER = logging.getLogger(__name__)

# PLN is not a standard HA currency unit constant, so we define it here
CURRENCY_PLN = "PLN"
UNIT_PLN_PER_KWH = f"{CURRENCY_PLN}/kWh"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Pstryk UPS sensor entities."""
    coordinator: PstrykUPSCoordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]

    async_add_entities(
        [
            CurrentPriceSensor(coordinator, entry),
            CurrentPowerSensor(coordinator, entry),
            ScheduleStatusSensor(coordinator, entry),
            NextChargeWindowSensor(coordinator, entry),
            NextDischargeWindowSensor(coordinator, entry),
            BatteryLevelSensor(coordinator, entry),
            DailySavingsSensor(coordinator, entry),
            PstrykAPIStatusSensor(coordinator, entry),
            ClaudeAPIStatusSensor(coordinator, entry),
        ]
    )


# ── Base class ────────────────────────────────────────────────────────────────

class PstrykUPSSensor(CoordinatorEntity[PstrykUPSCoordinator], SensorEntity):
    """Base sensor for the Pstryk UPS integration."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: PstrykUPSCoordinator,
        entry: ConfigEntry,
        unique_id_suffix: str,
    ) -> None:
        super().__init__(coordinator)
        ups_model: str = entry.data.get(CONF_UPS_MODEL, DEFAULT_UPS_MODEL)
        self._attr_unique_id = f"{entry.entry_id}_{unique_id_suffix}"
        self._attr_device_info = DeviceInfo(
            entry_type=DeviceEntryType.SERVICE,
            identifiers={(DOMAIN, entry.entry_id)},
            manufacturer=MANUFACTURER,
            model=ups_model,
            name=f"Pstryk UPS ({ups_model})",
            sw_version=VERSION,
            configuration_url="https://github.com/piotr-siedlak/hacs-pstryk-ups-ai",
        )

    @property
    def _coordinator_data(self) -> dict[str, Any]:
        return self.coordinator.data or {}


# ── Sensor implementations ──────────────────────────────────────────────────────

class CurrentPriceSensor(PstrykUPSSensor):
    """Current electricity price from Pstryk API (PLN/kWh)."""

    _attr_translation_key = "current_price"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 4

    def __init__(self, coordinator: PstrykUPSCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, SENSOR_CURRENT_PRICE)
        self._attr_native_unit_of_measurement = UNIT_PLN_PER_KWH

    @property
    def native_value(self) -> float | None:
        return self._coordinator_data.get("current_price")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        prices = self._coordinator_data.get("prices", [])
        last_refresh = self._coordinator_data.get("last_price_refresh")
        attrs: dict[str, Any] = {
            "price_count": len(prices),
            "last_refresh": last_refresh,
        }
        # Include the next 6 hourly prices for quick dashboard use
        if prices:
            now = datetime.now(timezone.utc)
            upcoming = [
                {"timestamp": p["timestamp"], "price": p["price"]}
                for p in prices
                if p.get("timestamp", "") >= now.strftime("%Y-%m-%dT%H:00:00Z")
            ][:6]
            attrs["upcoming_prices"] = upcoming
        return attrs


class CurrentPowerSensor(PstrykUPSSensor):
    """Current household power draw received via MQTT (kW)."""

    _attr_translation_key = "current_power"
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.KILO_WATT
    _attr_suggested_display_precision = 3

    def __init__(self, coordinator: PstrykUPSCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, SENSOR_CURRENT_POWER)

    @property
    def native_value(self) -> float:
        return self._coordinator_data.get("current_power_kw", 0.0)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        history = self.coordinator.power_history
        return {
            "history_daily_entries": len(history.get("daily", {})),
            "history_hourly_entries": len(history.get("hourly", {})),
        }


class ScheduleStatusSensor(PstrykUPSSensor):
    """Current scheduled action: charge / discharge / idle."""

    _attr_translation_key = "schedule_status"

    def __init__(self, coordinator: PstrykUPSCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, SENSOR_SCHEDULE_STATUS)

    @property
    def native_value(self) -> str:
        return self._coordinator_data.get("current_action", "idle")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        schedule = self._coordinator_data.get("schedule", [])
        # Expose full schedule as list attribute for Lovelace cards / automations
        return {
            "schedule": schedule,
            "schedule_hours": len(schedule),
            "auto_schedule_enabled": self._coordinator_data.get("auto_schedule_enabled", True),
        }

    @property
    def icon(self) -> str:
        action = self.native_value
        if action == "charge":
            return "mdi:battery-charging"
        if action == "discharge":
            return "mdi:battery-arrow-down"
        return "mdi:battery-clock"


class NextChargeWindowSensor(PstrykUPSSensor):
    """Timestamp of the next planned charging window."""

    _attr_translation_key = "next_charge_window"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: PstrykUPSCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, SENSOR_NEXT_CHARGE)

    @property
    def native_value(self) -> datetime | None:
        ts = self._coordinator_data.get("next_charge_window")
        if not ts:
            return None
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        schedule = self._coordinator_data.get("schedule", [])
        charge_windows = [
            {"hour": item["hour"], "price_pln_kwh": item.get("price_pln_kwh", 0),
             "power_kw": item.get("power_kw", 0), "reason": item.get("reason", "")}
            for item in schedule
            if item.get("action") == "charge"
        ]
        return {"charge_windows": charge_windows}


class NextDischargeWindowSensor(PstrykUPSSensor):
    """Timestamp of the next planned discharge window."""

    _attr_translation_key = "next_discharge_window"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: PstrykUPSCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, SENSOR_NEXT_DISCHARGE)

    @property
    def native_value(self) -> datetime | None:
        ts = self._coordinator_data.get("next_discharge_window")
        if not ts:
            return None
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        schedule = self._coordinator_data.get("schedule", [])
        discharge_windows = [
            {"hour": item["hour"], "price_pln_kwh": item.get("price_pln_kwh", 0),
             "power_kw": item.get("power_kw", 0), "reason": item.get("reason", "")}
            for item in schedule
            if item.get("action") == "discharge"
        ]
        return {"discharge_windows": discharge_windows}


class BatteryLevelSensor(PstrykUPSSensor):
    """UPS battery state of charge (%)."""

    _attr_translation_key = "battery_level"
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_suggested_display_precision = 1

    def __init__(self, coordinator: PstrykUPSCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, SENSOR_BATTERY_LEVEL)

    @property
    def native_value(self) -> float:
        return self._coordinator_data.get("battery_level_pct", 0.0)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        schedule = self._coordinator_data.get("schedule", [])
        # Find the projected battery level at end of schedule
        final_level: float | None = None
        if schedule:
            final_level = schedule[-1].get("battery_level_pct")
        return {"projected_end_level_pct": final_level}


class DailySavingsSensor(PstrykUPSSensor):
    """Estimated PLN saved today vs an all-idle baseline."""

    _attr_translation_key = "daily_savings"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator: PstrykUPSCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, SENSOR_DAILY_SAVINGS)
        self._attr_native_unit_of_measurement = CURRENCY_PLN

    @property
    def native_value(self) -> float:
        return self._coordinator_data.get("daily_savings_pln", 0.0)

    @property
    def icon(self) -> str:
        return "mdi:cash-plus"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        schedule = self._coordinator_data.get("schedule", [])
        charge_count = sum(1 for i in schedule if i.get("action") == "charge")
        discharge_count = sum(1 for i in schedule if i.get("action") == "discharge")
        return {
            "scheduled_charge_hours": charge_count,
            "scheduled_discharge_hours": discharge_count,
        }


class PstrykAPIStatusSensor(PstrykUPSSensor):
    """Shows whether the Pstryk electricity pricing API is reachable."""

    _attr_translation_key = "pstryk_api_status"

    def __init__(self, coordinator: PstrykUPSCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, SENSOR_PSTRYK_STATUS)

    @property
    def native_value(self) -> str:
        return self._coordinator_data.get("pstryk_api_status", "unknown")

    @property
    def icon(self) -> str:
        status = self.native_value
        if status == "ok":
            return "mdi:cloud-check"
        if status == "error":
            return "mdi:cloud-off-outline"
        return "mdi:cloud-question"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self._coordinator_data
        return {
            "last_request": data.get("pstryk_api_last_request", ""),
            "last_success": data.get("pstryk_api_last_success"),
            "last_error": data.get("pstryk_api_last_error"),
            "last_checked": data.get("pstryk_api_last_checked"),
            "next_day_prices_available": data.get("next_day_prices_available", False),
            "mqtt_status": data.get("mqtt_status", "unavailable"),
            "mqtt_power_topic": data.get("mqtt_power_topic", ""),
            "mqtt_last_power_update": data.get("mqtt_last_power_update"),
            "mqtt_history_topic": data.get("mqtt_history_topic", ""),
            "mqtt_last_history_update": data.get("mqtt_last_history_update"),
            "mqtt_charge_topic": data.get("mqtt_charge_topic", ""),
            "mqtt_discharge_topic": data.get("mqtt_discharge_topic", ""),
            "mqtt_battery_topic": data.get("mqtt_battery_topic", ""),
            "mqtt_last_battery_update": data.get("mqtt_last_battery_update"),
        }


class ClaudeAPIStatusSensor(PstrykUPSSensor):
    """Shows whether the Claude AI API is reachable and generating schedules."""

    _attr_translation_key = "claude_api_status"

    def __init__(self, coordinator: PstrykUPSCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, SENSOR_CLAUDE_STATUS)

    @property
    def native_value(self) -> str:
        return self._coordinator_data.get("claude_api_status", "unknown")

    @property
    def icon(self) -> str:
        status = self.native_value
        if status == "ok":
            return "mdi:robot"
        if status == "error":
            return "mdi:robot-dead"
        return "mdi:robot-outline"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self._coordinator_data
        return {
            "last_request": data.get("claude_last_request", ""),
            "last_success": data.get("claude_api_last_success"),
            "last_error": data.get("claude_api_last_error"),
            "schedule_source": data.get("claude_schedule_source", "unknown"),
            "last_prompt": data.get("claude_last_prompt", ""),
        }
