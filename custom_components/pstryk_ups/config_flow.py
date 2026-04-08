"""Config flow for the Pstryk UPS AI Optimizer integration."""
from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .claude_planner import ClaudePlanner
from .const import (
    CONF_BATTERY_CAPACITY,
    CONF_CLAUDE_API_KEY,
    CONF_MAX_CHARGE_RATE,
    CONF_MAX_DISCHARGE_RATE,
    CONF_MQTT_BATTERY_TOPIC,
    CONF_MQTT_CONTROL_TOPIC,
    CONF_MQTT_HISTORY_TOPIC,
    CONF_MQTT_POWER_TOPIC,
    CONF_NUM_STRINGS,
    CONF_PSTRYK_API_KEY,
    CONF_REFRESH_INTERVAL,
    CONF_UPS_MODEL,
    DEFAULT_BATTERY_CAPACITY,
    DEFAULT_MAX_CHARGE_RATE,
    DEFAULT_MAX_DISCHARGE_RATE,
    DEFAULT_NUM_STRINGS,
    DEFAULT_REFRESH_INTERVAL,
    DEFAULT_UPS_MODEL,
    DOMAIN,
)
from .pstryk_api import PstrykAPIClient, PstrykAuthError

_LOGGER = logging.getLogger(__name__)

# ── Shared schema fragments ──────────────────────────────────────────────────

_STEP_API_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_PSTRYK_API_KEY): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD)
        ),
        vol.Required(CONF_CLAUDE_API_KEY): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD)
        ),
    }
)

_STEP_UPS_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_UPS_MODEL, default=DEFAULT_UPS_MODEL): str,
        vol.Required(CONF_BATTERY_CAPACITY, default=DEFAULT_BATTERY_CAPACITY): NumberSelector(
            NumberSelectorConfig(min=0.5, max=1000.0, step=0.5, unit_of_measurement="kWh", mode=NumberSelectorMode.BOX)
        ),
        vol.Required(CONF_NUM_STRINGS, default=DEFAULT_NUM_STRINGS): NumberSelector(
            NumberSelectorConfig(min=1, max=100, step=1, mode=NumberSelectorMode.BOX)
        ),
        vol.Required(CONF_MAX_CHARGE_RATE, default=DEFAULT_MAX_CHARGE_RATE): NumberSelector(
            NumberSelectorConfig(min=0.1, max=100.0, step=0.1, unit_of_measurement="kW", mode=NumberSelectorMode.BOX)
        ),
        vol.Required(CONF_MAX_DISCHARGE_RATE, default=DEFAULT_MAX_DISCHARGE_RATE): NumberSelector(
            NumberSelectorConfig(min=0.1, max=100.0, step=0.1, unit_of_measurement="kW", mode=NumberSelectorMode.BOX)
        ),
    }
)

_STEP_MQTT_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_MQTT_POWER_TOPIC): str,
        vol.Required(CONF_MQTT_HISTORY_TOPIC): str,
        vol.Required(CONF_MQTT_CONTROL_TOPIC): str,
        vol.Optional(CONF_MQTT_BATTERY_TOPIC, default=""): str,
        vol.Required(CONF_REFRESH_INTERVAL, default=DEFAULT_REFRESH_INTERVAL): NumberSelector(
            NumberSelectorConfig(min=1, max=24, step=1, unit_of_measurement="h", mode=NumberSelectorMode.BOX)
        ),
    }
)


# ── Helper ───────────────────────────────────────────────────────────────────

async def _validate_api_keys(
    hass: HomeAssistant,
    pstryk_key: str,
    claude_key: str,
) -> dict[str, str]:
    """Validate both API keys; return a dict of field → error code on failure."""
    errors: dict[str, str] = {}
    session = async_get_clientsession(hass)
    pstryk_client = PstrykAPIClient(api_key=pstryk_key, session=session)

    try:
        valid = await pstryk_client.async_validate_key()
        if not valid:
            errors[CONF_PSTRYK_API_KEY] = "invalid_pstryk_key"
    except PstrykAuthError:
        errors[CONF_PSTRYK_API_KEY] = "invalid_pstryk_key"
    except aiohttp.ClientError:
        errors[CONF_PSTRYK_API_KEY] = "cannot_connect"

    if CONF_PSTRYK_API_KEY not in errors:
        # Only validate Claude key when Pstryk is fine (avoid double-fail UX)
        claude_planner = ClaudePlanner(api_key=claude_key, ups_config={})
        valid = await claude_planner.async_validate_key()
        if not valid:
            errors[CONF_CLAUDE_API_KEY] = "invalid_claude_key"

    return errors


# ── Config flow ───────────────────────────────────────────────────────────────

class PstrykUPSConfigFlow(ConfigFlow, domain=DOMAIN):
    """Three-step config flow: API keys → UPS params → MQTT & scheduling."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    # ── Step 1: API keys ─────────────────────────────────────────────────────

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            pstryk_key = user_input[CONF_PSTRYK_API_KEY].strip()
            claude_key = user_input[CONF_CLAUDE_API_KEY].strip()

            if not pstryk_key:
                errors[CONF_PSTRYK_API_KEY] = "required"
            if not claude_key:
                errors[CONF_CLAUDE_API_KEY] = "required"

            if not errors:
                errors = await _validate_api_keys(self.hass, pstryk_key, claude_key)

            if not errors:
                self._data.update(
                    {
                        CONF_PSTRYK_API_KEY: pstryk_key,
                        CONF_CLAUDE_API_KEY: claude_key,
                    }
                )
                return await self.async_step_ups_config()

        return self.async_show_form(
            step_id="user",
            data_schema=_STEP_API_SCHEMA,
            errors=errors,
        )

    # ── Step 2: UPS parameters ───────────────────────────────────────────────

    async def async_step_ups_config(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._data.update(
                {
                    CONF_UPS_MODEL: user_input.get(CONF_UPS_MODEL, DEFAULT_UPS_MODEL),
                    CONF_BATTERY_CAPACITY: float(user_input[CONF_BATTERY_CAPACITY]),
                    CONF_NUM_STRINGS: int(user_input[CONF_NUM_STRINGS]),
                    CONF_MAX_CHARGE_RATE: float(user_input[CONF_MAX_CHARGE_RATE]),
                    CONF_MAX_DISCHARGE_RATE: float(user_input[CONF_MAX_DISCHARGE_RATE]),
                }
            )
            return await self.async_step_mqtt_schedule()

        return self.async_show_form(
            step_id="ups_config",
            data_schema=_STEP_UPS_SCHEMA,
        )

    # ── Step 3: MQTT topics & scheduling ────────────────────────────────────

    async def async_step_mqtt_schedule(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            power_topic = user_input[CONF_MQTT_POWER_TOPIC].strip()
            history_topic = user_input[CONF_MQTT_HISTORY_TOPIC].strip()
            control_topic = user_input[CONF_MQTT_CONTROL_TOPIC].strip()

            if not power_topic:
                errors[CONF_MQTT_POWER_TOPIC] = "required"
            if not history_topic:
                errors[CONF_MQTT_HISTORY_TOPIC] = "required"
            if not control_topic:
                errors[CONF_MQTT_CONTROL_TOPIC] = "required"

            if not errors:
                self._data.update(
                    {
                        CONF_MQTT_POWER_TOPIC: power_topic,
                        CONF_MQTT_HISTORY_TOPIC: history_topic,
                        CONF_MQTT_CONTROL_TOPIC: control_topic,
                        CONF_MQTT_BATTERY_TOPIC: user_input.get(CONF_MQTT_BATTERY_TOPIC, "").strip(),
                        CONF_REFRESH_INTERVAL: int(user_input[CONF_REFRESH_INTERVAL]),
                    }
                )
                ups_model: str = self._data.get(CONF_UPS_MODEL, DEFAULT_UPS_MODEL)
                return self.async_create_entry(
                    title=f"Pstryk UPS ({ups_model})",
                    data=self._data,
                )

        return self.async_show_form(
            step_id="mqtt_schedule",
            data_schema=_STEP_MQTT_SCHEMA,
            errors=errors,
        )

    # ── Reconfigure (edit existing entry) ───────────────────────────────────

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Allow editing all settings without removing the integration."""
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        if entry is None:
            return self.async_abort(reason="entry_not_found")

        # Pre-populate with existing values
        self._data = dict(entry.data)

        if user_input is not None:
            # Re-run as a fresh user step but update in place
            return await self.async_step_user(user_input)

        existing_schema = vol.Schema(
            {
                vol.Required(
                    CONF_PSTRYK_API_KEY,
                    default=entry.data.get(CONF_PSTRYK_API_KEY, ""),
                ): TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD)),
                vol.Required(
                    CONF_CLAUDE_API_KEY,
                    default=entry.data.get(CONF_CLAUDE_API_KEY, ""),
                ): TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD)),
            }
        )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=existing_schema,
        )

    async def async_step_reconfigure_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Finish reconfigure by updating the entry data."""
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        if entry is None:
            return self.async_abort(reason="entry_not_found")

        if user_input is not None:
            updated = dict(entry.data)
            updated.update(self._data)
            return self.async_update_reload_and_abort(
                entry,
                data=updated,
                reason="reconfigure_successful",
            )

        return self.async_abort(reason="reconfigure_successful")
