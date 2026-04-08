"""Switch platform for the Pstryk UPS AI Optimizer integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_MQTT_CONTROL_TOPIC,
    CONF_UPS_MODEL,
    DATA_COORDINATOR,
    DEFAULT_UPS_MODEL,
    DOMAIN,
    MANUFACTURER,
    SWITCH_AUTO_SCHEDULE,
    SWITCH_CHARGING,
    VERSION,
)
from .coordinator import PstrykUPSCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Pstryk UPS switch entities."""
    coordinator: PstrykUPSCoordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]

    async_add_entities(
        [
            ChargingSwitch(coordinator, entry),
            AutoScheduleSwitch(coordinator, entry),
        ]
    )


# ── Base class ────────────────────────────────────────────────────────────────

class PstrykUPSSwitch(CoordinatorEntity[PstrykUPSCoordinator], SwitchEntity):
    """Base switch for the Pstryk UPS integration."""

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


# ── Switch implementations ────────────────────────────────────────────────────

class ChargingSwitch(PstrykUPSSwitch):
    """Toggle UPS battery charging on/off.

    When Auto-schedule is active the switch reflects the schedule.
    The user can override it at any time; the override persists until the
    next coordinator refresh cycle (hourly) when auto-schedule re-applies.
    """

    _attr_translation_key = "charging"
    _attr_device_class = SwitchDeviceClass.SWITCH

    def __init__(self, coordinator: PstrykUPSCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, SWITCH_CHARGING)
        self._control_topic: str = entry.data.get(CONF_MQTT_CONTROL_TOPIC, "")

    @property
    def is_on(self) -> bool:
        return self._coordinator_data.get("charging_enabled", False)

    @property
    def icon(self) -> str:
        return "mdi:battery-charging" if self.is_on else "mdi:battery-off"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self._coordinator_data
        return {
            "auto_schedule_active": data.get("auto_schedule_enabled", True),
            "current_schedule_action": data.get("current_action", "idle"),
            "control_topic": self._control_topic,
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable UPS charging and publish MQTT command."""
        _LOGGER.info("User enabled UPS charging")
        await self.coordinator.set_charging(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable UPS charging and publish MQTT command."""
        _LOGGER.info("User disabled UPS charging")
        await self.coordinator.set_charging(False)


class AutoScheduleSwitch(PstrykUPSSwitch):
    """Enable or disable the AI-driven automatic charging schedule.

    When ON  – the coordinator automatically sets charging_enabled each hour
               based on Claude's planned schedule.
    When OFF – the user has full manual control via the ChargingSwitch.
    """

    _attr_translation_key = "auto_schedule"
    _attr_device_class = SwitchDeviceClass.SWITCH

    def __init__(self, coordinator: PstrykUPSCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, SWITCH_AUTO_SCHEDULE)

    @property
    def is_on(self) -> bool:
        return self._coordinator_data.get("auto_schedule_enabled", True)

    @property
    def icon(self) -> str:
        return "mdi:robot" if self.is_on else "mdi:robot-off"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self._coordinator_data
        schedule = data.get("schedule", [])
        return {
            "schedule_hours_planned": len(schedule),
            "next_charge_window": data.get("next_charge_window"),
            "next_discharge_window": data.get("next_discharge_window"),
            "daily_savings_pln": data.get("daily_savings_pln", 0.0),
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable automatic scheduling."""
        _LOGGER.info("Automatic UPS schedule enabled")
        await self.coordinator.set_auto_schedule(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable automatic scheduling — manual control only."""
        _LOGGER.info("Automatic UPS schedule disabled (manual mode)")
        await self.coordinator.set_auto_schedule(False)
