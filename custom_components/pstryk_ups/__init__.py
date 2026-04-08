"""Pstryk UPS AI Optimizer — Home Assistant integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .const import DATA_COORDINATOR, DOMAIN, PLATFORMS
from .coordinator import PstrykUPSCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Pstryk UPS AI Optimizer from a config entry.

    Sequence
    --------
    1. Instantiate the coordinator (holds all runtime state).
    2. Set up MQTT subscriptions (fire-and-forget in case MQTT is slow).
    3. Run the first data refresh — raises ConfigEntryNotReady on hard errors.
    4. Forward setup to sensor and switch platforms.
    5. Register an update listener so the entry reloads on option changes.
    """
    coordinator = PstrykUPSCoordinator(hass, entry)

    # Subscribe to MQTT topics (best-effort; MQTT may not have data yet)
    try:
        await coordinator.async_setup_mqtt()
    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning("MQTT setup error (will retry): %s", exc)

    # First data fetch; raises UpdateFailed → ConfigEntryNotReady on failure
    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception as exc:
        raise ConfigEntryNotReady(
            f"Initial data fetch failed: {exc}"
        ) from exc

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        DATA_COORDINATOR: coordinator,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Reload entry when its data is updated (e.g. from reconfigure flow)
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))

    _LOGGER.info("Pstryk UPS AI Optimizer set up successfully for entry %s", entry.entry_id)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry cleanly."""
    coordinator: PstrykUPSCoordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]

    # Unforward platforms first so entities can clean up
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    # Cancel MQTT subscriptions
    await coordinator.async_unload()

    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)

    return unload_ok


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the config entry when its options/data change."""
    _LOGGER.debug("Reloading Pstryk UPS entry %s", entry.entry_id)
    await hass.config_entries.async_reload(entry.entry_id)
