"""Config flow for the Pstryk UPS AI Optimizer integration."""
from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import HomeAssistant, callback
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
    CONF_BATTERY_MAX_PCT,
    CONF_BATTERY_MIN_PCT,
    CONF_CLAUDE_API_KEY,
    CONF_MAX_CHARGE_RATE,
    CONF_MAX_DISCHARGE_RATE,
    CONF_MQTT_BATTERY_TOPIC,
    CONF_MQTT_CHARGE_TOPIC,
    CONF_MQTT_DISCHARGE_TOPIC,
    CONF_MQTT_HISTORY_TOPIC,
    CONF_MQTT_POWER_TOPIC,
    CONF_NUM_STRINGS,
    CONF_PSTRYK_API_KEY,
    CONF_REFRESH_INTERVAL,
    CONF_UPS_MODEL,
    DEFAULT_BATTERY_CAPACITY,
    DEFAULT_BATTERY_MAX_PCT,
    DEFAULT_BATTERY_MIN_PCT,
    DEFAULT_MAX_CHARGE_RATE,
    DEFAULT_MAX_DISCHARGE_RATE,
    DEFAULT_NUM_STRINGS,
    DEFAULT_REFRESH_INTERVAL,
    DEFAULT_UPS_MODEL,
    DOMAIN,
)
from .pstryk_api import PstrykAPIClient, PstrykAuthError

_LOGGER = logging.getLogger(__name__)


# ── Schema builders ──────────────────────────────────────────────────────────
# Built as functions so that current values can be injected as defaults.

def _api_schema(
    pstryk_default: str = "",
    claude_default: str = "",
) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_PSTRYK_API_KEY, default=pstryk_default): TextSelector(
                TextSelectorConfig(type=TextSelectorType.PASSWORD)
            ),
            vol.Required(CONF_CLAUDE_API_KEY, default=claude_default): TextSelector(
                TextSelectorConfig(type=TextSelectorType.PASSWORD)
            ),
        }
    )


def _ups_schema(
    ups_model: str = DEFAULT_UPS_MODEL,
    battery_capacity: float = DEFAULT_BATTERY_CAPACITY,
    num_strings: int = DEFAULT_NUM_STRINGS,
    max_charge_rate: float = DEFAULT_MAX_CHARGE_RATE,
    max_discharge_rate: float = DEFAULT_MAX_DISCHARGE_RATE,
    battery_min_pct: float = DEFAULT_BATTERY_MIN_PCT,
    battery_max_pct: float = DEFAULT_BATTERY_MAX_PCT,
) -> vol.Schema:
    return vol.Schema(
        {
            vol.Optional(CONF_UPS_MODEL, default=ups_model): str,
            vol.Required(CONF_BATTERY_CAPACITY, default=battery_capacity): NumberSelector(
                NumberSelectorConfig(min=0.5, max=1000.0, step=0.5, unit_of_measurement="kWh", mode=NumberSelectorMode.BOX)
            ),
            vol.Required(CONF_NUM_STRINGS, default=num_strings): NumberSelector(
                NumberSelectorConfig(min=1, max=100, step=1, mode=NumberSelectorMode.BOX)
            ),
            vol.Required(CONF_MAX_CHARGE_RATE, default=max_charge_rate): NumberSelector(
                NumberSelectorConfig(min=0.1, max=100.0, step=0.1, unit_of_measurement="kW", mode=NumberSelectorMode.BOX)
            ),
            vol.Required(CONF_MAX_DISCHARGE_RATE, default=max_discharge_rate): NumberSelector(
                NumberSelectorConfig(min=0.1, max=100.0, step=0.1, unit_of_measurement="kW", mode=NumberSelectorMode.BOX)
            ),
            vol.Required(CONF_BATTERY_MIN_PCT, default=battery_min_pct): NumberSelector(
                NumberSelectorConfig(min=0.0, max=50.0, step=1.0, unit_of_measurement="%", mode=NumberSelectorMode.BOX)
            ),
            vol.Required(CONF_BATTERY_MAX_PCT, default=battery_max_pct): NumberSelector(
                NumberSelectorConfig(min=50.0, max=100.0, step=1.0, unit_of_measurement="%", mode=NumberSelectorMode.BOX)
            ),
        }
    )


def _mqtt_schema(
    power_topic: str = "",
    history_topic: str = "",
    charge_topic: str = "",
    discharge_topic: str = "",
    battery_topic: str = "",
    refresh_interval: int = DEFAULT_REFRESH_INTERVAL,
) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_MQTT_POWER_TOPIC, default=power_topic): str,
            vol.Required(CONF_MQTT_HISTORY_TOPIC, default=history_topic): str,
            vol.Required(CONF_MQTT_CHARGE_TOPIC, default=charge_topic): str,
            vol.Required(CONF_MQTT_DISCHARGE_TOPIC, default=discharge_topic): str,
            vol.Required(CONF_MQTT_BATTERY_TOPIC, default=battery_topic): str,
            vol.Required(CONF_REFRESH_INTERVAL, default=refresh_interval): NumberSelector(
                NumberSelectorConfig(min=1, max=24, step=1, unit_of_measurement="h", mode=NumberSelectorMode.BOX)
            ),
        }
    )


# ── Validation helper ────────────────────────────────────────────────────────

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
        claude_planner = ClaudePlanner(api_key=claude_key, ups_config={})
        valid = await claude_planner.async_validate_key()
        if not valid:
            errors[CONF_CLAUDE_API_KEY] = "invalid_claude_key"

    return errors


def _parse_ups_input(user_input: dict[str, Any]) -> dict[str, Any]:
    return {
        CONF_UPS_MODEL: user_input.get(CONF_UPS_MODEL, DEFAULT_UPS_MODEL),
        CONF_BATTERY_CAPACITY: float(user_input[CONF_BATTERY_CAPACITY]),
        CONF_NUM_STRINGS: int(user_input[CONF_NUM_STRINGS]),
        CONF_MAX_CHARGE_RATE: float(user_input[CONF_MAX_CHARGE_RATE]),
        CONF_MAX_DISCHARGE_RATE: float(user_input[CONF_MAX_DISCHARGE_RATE]),
        CONF_BATTERY_MIN_PCT: float(user_input[CONF_BATTERY_MIN_PCT]),
        CONF_BATTERY_MAX_PCT: float(user_input[CONF_BATTERY_MAX_PCT]),
    }


def _parse_mqtt_input(user_input: dict[str, Any]) -> dict[str, Any]:
    return {
        CONF_MQTT_POWER_TOPIC: user_input[CONF_MQTT_POWER_TOPIC].strip(),
        CONF_MQTT_HISTORY_TOPIC: user_input[CONF_MQTT_HISTORY_TOPIC].strip(),
        CONF_MQTT_CHARGE_TOPIC: user_input[CONF_MQTT_CHARGE_TOPIC].strip(),
        CONF_MQTT_DISCHARGE_TOPIC: user_input[CONF_MQTT_DISCHARGE_TOPIC].strip(),
        CONF_MQTT_BATTERY_TOPIC: user_input.get(CONF_MQTT_BATTERY_TOPIC, "").strip(),
        CONF_REFRESH_INTERVAL: int(user_input[CONF_REFRESH_INTERVAL]),
    }


# ── Main config flow ─────────────────────────────────────────────────────────

class PstrykUPSConfigFlow(ConfigFlow, domain=DOMAIN):
    """Three-step config flow: API keys → UPS params → MQTT & scheduling."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> PstrykUPSOptionsFlowHandler:
        """Return the options flow handler for changing topics and UPS params."""
        return PstrykUPSOptionsFlowHandler()

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
                    {CONF_PSTRYK_API_KEY: pstryk_key, CONF_CLAUDE_API_KEY: claude_key}
                )
                return await self.async_step_ups_config()

        return self.async_show_form(
            step_id="user",
            data_schema=_api_schema(),
            errors=errors,
        )

    # ── Step 2: UPS parameters ───────────────────────────────────────────────

    async def async_step_ups_config(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._data.update(_parse_ups_input(user_input))
            return await self.async_step_mqtt_schedule()

        return self.async_show_form(
            step_id="ups_config",
            data_schema=_ups_schema(),
        )

    # ── Step 3: MQTT topics & scheduling ─────────────────────────────────────

    async def async_step_mqtt_schedule(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            parsed = _parse_mqtt_input(user_input)
            if not parsed[CONF_MQTT_POWER_TOPIC]:
                errors[CONF_MQTT_POWER_TOPIC] = "required"
            if not parsed[CONF_MQTT_HISTORY_TOPIC]:
                errors[CONF_MQTT_HISTORY_TOPIC] = "required"
            if not parsed[CONF_MQTT_CHARGE_TOPIC]:
                errors[CONF_MQTT_CHARGE_TOPIC] = "required"
            if not parsed[CONF_MQTT_DISCHARGE_TOPIC]:
                errors[CONF_MQTT_DISCHARGE_TOPIC] = "required"

            if not errors:
                self._data.update(parsed)
                ups_model: str = self._data.get(CONF_UPS_MODEL, DEFAULT_UPS_MODEL)
                return self.async_create_entry(
                    title=f"Pstryk UPS ({ups_model})",
                    data=self._data,
                )

        return self.async_show_form(
            step_id="mqtt_schedule",
            data_schema=_mqtt_schema(
                power_topic=self._data.get(CONF_MQTT_POWER_TOPIC, ""),
                history_topic=self._data.get(CONF_MQTT_HISTORY_TOPIC, ""),
                charge_topic=self._data.get(CONF_MQTT_CHARGE_TOPIC, ""),
                discharge_topic=self._data.get(CONF_MQTT_DISCHARGE_TOPIC, ""),
            ),
            errors=errors,
        )

    # ── Reconfigure: update API keys (keeps UPS/MQTT settings intact) ────────

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Allow updating API keys without removing the integration."""
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        if entry is None:
            return self.async_abort(reason="entry_not_found")

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
                updated_data = {
                    **entry.data,
                    CONF_PSTRYK_API_KEY: pstryk_key,
                    CONF_CLAUDE_API_KEY: claude_key,
                }
                return self.async_update_reload_and_abort(
                    entry,
                    data=updated_data,
                    reason="reconfigure_successful",
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_api_schema(
                pstryk_default=entry.data.get(CONF_PSTRYK_API_KEY, ""),
                claude_default=entry.data.get(CONF_CLAUDE_API_KEY, ""),
            ),
            errors=errors,
        )


# ── Options flow ─────────────────────────────────────────────────────────────

def _options_schema(
    ups_model: str = DEFAULT_UPS_MODEL,
    battery_capacity: float = DEFAULT_BATTERY_CAPACITY,
    num_strings: int = DEFAULT_NUM_STRINGS,
    max_charge_rate: float = DEFAULT_MAX_CHARGE_RATE,
    max_discharge_rate: float = DEFAULT_MAX_DISCHARGE_RATE,
    battery_min_pct: float = DEFAULT_BATTERY_MIN_PCT,
    battery_max_pct: float = DEFAULT_BATTERY_MAX_PCT,
    power_topic: str = "",
    history_topic: str = "",
    charge_topic: str = "",
    discharge_topic: str = "",
    battery_topic: str = "",
    refresh_interval: int = DEFAULT_REFRESH_INTERVAL,
) -> vol.Schema:
    """Combined schema for the single-page options flow."""
    return vol.Schema(
        {
            # ── UPS parameters ──────────────────────────────────────────────
            vol.Optional(CONF_UPS_MODEL, default=ups_model): str,
            vol.Required(CONF_BATTERY_CAPACITY, default=battery_capacity): NumberSelector(
                NumberSelectorConfig(min=0.5, max=1000.0, step=0.5, unit_of_measurement="kWh", mode=NumberSelectorMode.BOX)
            ),
            vol.Required(CONF_NUM_STRINGS, default=num_strings): NumberSelector(
                NumberSelectorConfig(min=1, max=100, step=1, mode=NumberSelectorMode.BOX)
            ),
            vol.Required(CONF_MAX_CHARGE_RATE, default=max_charge_rate): NumberSelector(
                NumberSelectorConfig(min=0.1, max=100.0, step=0.1, unit_of_measurement="kW", mode=NumberSelectorMode.BOX)
            ),
            vol.Required(CONF_MAX_DISCHARGE_RATE, default=max_discharge_rate): NumberSelector(
                NumberSelectorConfig(min=0.1, max=100.0, step=0.1, unit_of_measurement="kW", mode=NumberSelectorMode.BOX)
            ),
            vol.Required(CONF_BATTERY_MIN_PCT, default=battery_min_pct): NumberSelector(
                NumberSelectorConfig(min=0.0, max=50.0, step=1.0, unit_of_measurement="%", mode=NumberSelectorMode.BOX)
            ),
            vol.Required(CONF_BATTERY_MAX_PCT, default=battery_max_pct): NumberSelector(
                NumberSelectorConfig(min=50.0, max=100.0, step=1.0, unit_of_measurement="%", mode=NumberSelectorMode.BOX)
            ),
            # ── MQTT topics ─────────────────────────────────────────────────
            vol.Required(CONF_MQTT_POWER_TOPIC, default=power_topic): str,
            vol.Required(CONF_MQTT_HISTORY_TOPIC, default=history_topic): str,
            vol.Required(CONF_MQTT_CHARGE_TOPIC, default=charge_topic): str,
            vol.Required(CONF_MQTT_DISCHARGE_TOPIC, default=discharge_topic): str,
            vol.Required(CONF_MQTT_BATTERY_TOPIC, default=battery_topic): str,
            vol.Required(CONF_REFRESH_INTERVAL, default=refresh_interval): NumberSelector(
                NumberSelectorConfig(min=1, max=24, step=1, unit_of_measurement="h", mode=NumberSelectorMode.BOX)
            ),
        }
    )


class PstrykUPSOptionsFlowHandler(OptionsFlow):
    """Options flow: change all UPS and MQTT settings without re-adding.

    Single-page form accessible via Settings → Devices & Services →
    Pstryk UPS AI Optimizer → Configure.
    """

    def _merged(self) -> dict[str, Any]:
        """Return current config with existing options already applied."""
        return {**self.config_entry.data, **self.config_entry.options}

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Single step: all UPS parameters and MQTT topics on one page."""
        errors: dict[str, str] = {}

        if user_input is not None:
            ups = _parse_ups_input(user_input)
            mqtt = _parse_mqtt_input(user_input)

            if not mqtt[CONF_MQTT_POWER_TOPIC]:
                errors[CONF_MQTT_POWER_TOPIC] = "required"
            if not mqtt[CONF_MQTT_HISTORY_TOPIC]:
                errors[CONF_MQTT_HISTORY_TOPIC] = "required"
            if not mqtt[CONF_MQTT_CHARGE_TOPIC]:
                errors[CONF_MQTT_CHARGE_TOPIC] = "required"
            if not mqtt[CONF_MQTT_DISCHARGE_TOPIC]:
                errors[CONF_MQTT_DISCHARGE_TOPIC] = "required"
            if not mqtt[CONF_MQTT_BATTERY_TOPIC]:
                errors[CONF_MQTT_BATTERY_TOPIC] = "required"

            if not errors:
                return self.async_create_entry(data={**ups, **mqtt})

        current = self._merged()
        return self.async_show_form(
            step_id="init",
            data_schema=_options_schema(
                ups_model=current.get(CONF_UPS_MODEL, DEFAULT_UPS_MODEL),
                battery_capacity=current.get(CONF_BATTERY_CAPACITY, DEFAULT_BATTERY_CAPACITY),
                num_strings=current.get(CONF_NUM_STRINGS, DEFAULT_NUM_STRINGS),
                max_charge_rate=current.get(CONF_MAX_CHARGE_RATE, DEFAULT_MAX_CHARGE_RATE),
                max_discharge_rate=current.get(CONF_MAX_DISCHARGE_RATE, DEFAULT_MAX_DISCHARGE_RATE),
                battery_min_pct=current.get(CONF_BATTERY_MIN_PCT, DEFAULT_BATTERY_MIN_PCT),
                battery_max_pct=current.get(CONF_BATTERY_MAX_PCT, DEFAULT_BATTERY_MAX_PCT),
                power_topic=current.get(CONF_MQTT_POWER_TOPIC, ""),
                history_topic=current.get(CONF_MQTT_HISTORY_TOPIC, ""),
                charge_topic=current.get(CONF_MQTT_CHARGE_TOPIC, ""),
                discharge_topic=current.get(CONF_MQTT_DISCHARGE_TOPIC, ""),
                battery_topic=current.get(CONF_MQTT_BATTERY_TOPIC, ""),
                refresh_interval=current.get(CONF_REFRESH_INTERVAL, DEFAULT_REFRESH_INTERVAL),
            ),
            errors=errors,
        )
