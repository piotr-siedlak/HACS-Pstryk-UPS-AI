"""Button platform for the Pstryk UPS AI Optimizer integration."""
from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    BUTTON_REFRESH_PRICES,
    CONF_UPS_MODEL,
    DATA_COORDINATOR,
    DEFAULT_UPS_MODEL,
    DOMAIN,
    MANUFACTURER,
    VERSION,
)
from .coordinator import PstrykUPSCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Pstryk UPS button entities."""
    coordinator: PstrykUPSCoordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    async_add_entities([RefreshPricesButton(coordinator, entry)])


class RefreshPricesButton(ButtonEntity):
    """Button that immediately fetches fresh prices from the Pstryk API.

    Pressing this bypasses the configured refresh interval TTL and forces
    an API call right now, followed by a schedule regeneration via Claude
    (or the heuristic fallback). The automatic hourly schedule is unaffected.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "refresh_prices"
    _attr_icon = "mdi:refresh"

    def __init__(self, coordinator: PstrykUPSCoordinator, entry: ConfigEntry) -> None:
        ups_model: str = entry.data.get(CONF_UPS_MODEL, DEFAULT_UPS_MODEL)
        self._coordinator = coordinator
        self._attr_unique_id = f"{entry.entry_id}_{BUTTON_REFRESH_PRICES}"
        self._attr_device_info = DeviceInfo(
            entry_type=DeviceEntryType.SERVICE,
            identifiers={(DOMAIN, entry.entry_id)},
            manufacturer=MANUFACTURER,
            model=ups_model,
            name=f"Pstryk UPS ({ups_model})",
            sw_version=VERSION,
            configuration_url="https://github.com/piotr-siedlak/hacs-pstryk-ups-ai",
        )

    async def async_press(self) -> None:
        """Force an immediate Pstryk API price fetch and schedule regeneration."""
        _LOGGER.info("Manual Pstryk price refresh triggered by user")
        # Reset the TTL so _needs_price_refresh() returns True immediately
        self._coordinator.last_price_refresh = None
        # Trigger a full coordinator refresh cycle
        await self._coordinator.async_refresh()
