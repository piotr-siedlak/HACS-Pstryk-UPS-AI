"""DataUpdateCoordinator for the Pstryk UPS AI Optimizer integration."""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from homeassistant.components import mqtt
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .claude_planner import ClaudePlanner
from .const import (
    ACTION_CHARGE,
    ACTION_DISCHARGE,
    ACTION_IDLE,
    CONF_BATTERY_CAPACITY,
    CONF_BATTERY_MAX_PCT,
    CONF_BATTERY_MIN_PCT,
    CONF_CLAUDE_API_KEY,
    CONF_CLAUDE_PROMPT,
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
    DEFAULT_BATTERY_MAX_PCT,
    DEFAULT_BATTERY_MIN_PCT,
    DEFAULT_REFRESH_INTERVAL,
    DOMAIN,
    MQTT_PAYLOAD_OFF,
    MQTT_PAYLOAD_ON,
    NEXT_DAY_PRICES_HOUR,
    UPDATE_INTERVAL_HOURS,
    WARSAW_TZ_NAME,
)
from .pstryk_api import PstrykAPIClient, PstrykAPIError

_LOGGER = logging.getLogger(__name__)


class PstrykUPSCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Central coordinator that owns all integration state.

    Responsibilities
    ----------------
    - Poll Pstryk API for electricity prices (rate-limited by CONF_REFRESH_INTERVAL).
    - Subscribe to MQTT topics for real-time power draw, consumption history,
      and optional battery level.
    - Run the Claude planner (or heuristic fallback) whenever fresh prices arrive.
    - Maintain ``charging_enabled`` and ``auto_schedule_enabled`` flags.
    - Publish ON/OFF commands to the UPS charge-control MQTT topic.
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        # Options (set via the Configure button) override the original data so
        # users can change topics and UPS params without re-adding the entry.
        self.config = {**entry.data, **entry.options}

        refresh_interval_h: int = self.config.get(CONF_REFRESH_INTERVAL, DEFAULT_REFRESH_INTERVAL)
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{entry.entry_id}",
            update_interval=timedelta(hours=UPDATE_INTERVAL_HOURS),
        )

        # ── Runtime state ───────────────────────────────────────────────────
        self.prices: list[dict[str, Any]] = []
        self.schedule: list[dict[str, Any]] = []
        self.current_power_kw: float = 0.0
        self.battery_level_pct: float = 50.0
        self.power_history: dict[str, Any] = {"daily": {}, "hourly": {}}
        self.charging_enabled: bool = False
        self.discharging_enabled: bool = False
        self.auto_schedule_enabled: bool = True
        self.last_price_refresh: datetime | None = None

        # PLN saved today (computed from schedule vs idle baseline)
        self.daily_savings_pln: float = 0.0

        # API status tracking — exposed via status sensor entities
        self.pstryk_api_status: str = "unknown"
        self.pstryk_api_last_error: str | None = None
        self.pstryk_api_last_success: datetime | None = None
        self.pstryk_api_last_checked: datetime | None = None
        self.claude_api_status: str = "unknown"
        self.claude_api_last_error: str | None = None
        self.claude_api_last_success: datetime | None = None
        self.claude_schedule_source: str = "unknown"
        self.claude_last_prompt: str = ""

        # MQTT per-topic last-update timestamps
        self.mqtt_last_power_update: datetime | None = None
        self.mqtt_last_history_update: datetime | None = None
        self.mqtt_last_battery_update: datetime | None = None

        # How often (hours) to call the Pstryk API
        self._price_refresh_interval = timedelta(hours=refresh_interval_h)

        # Track whether we already fetched next-day prices today (Warsaw date).
        # TGE publishes next-day prices around 14–15:00 Warsaw; we force one
        # extra refresh after NEXT_DAY_PRICES_HOUR if this is still None / stale.
        self._next_day_prices_fetched_date: date | None = None
        self._warsaw = ZoneInfo(WARSAW_TZ_NAME)

        # MQTT status — "connected" | "no_topics" | "unavailable"
        self.mqtt_status: str = "unavailable"

        # MQTT subscription cancel callbacks
        self._mqtt_unsubs: list[Any] = []

        # Build sub-clients
        session = async_get_clientsession(hass)
        self._pstryk = PstrykAPIClient(
            api_key=self.config[CONF_PSTRYK_API_KEY],
            session=session,
        )
        ups_cfg = {
            "ups_model": self.config.get(CONF_UPS_MODEL, "Generic UPS"),
            "battery_capacity_kwh": self.config.get(CONF_BATTERY_CAPACITY, 10.0),
            "num_strings": self.config.get(CONF_NUM_STRINGS, 1),
            "max_charge_rate_kw": self.config.get(CONF_MAX_CHARGE_RATE, 2.0),
            "max_discharge_rate_kw": self.config.get(CONF_MAX_DISCHARGE_RATE, 2.0),
            "battery_min_pct": self.config.get(CONF_BATTERY_MIN_PCT, DEFAULT_BATTERY_MIN_PCT),
            "battery_max_pct": self.config.get(CONF_BATTERY_MAX_PCT, DEFAULT_BATTERY_MAX_PCT),
        }
        self._planner = ClaudePlanner(
            api_key=self.config[CONF_CLAUDE_API_KEY],
            ups_config=ups_cfg,
        )

    # ── MQTT lifecycle ──────────────────────────────────────────────────────

    def _mqtt_available(self) -> bool:
        """Return True when the MQTT integration is loaded and ready."""
        return mqtt.DOMAIN in self.hass.config.components

    async def async_setup_mqtt(self) -> None:
        """Subscribe to all configured MQTT topics. Call once during setup."""
        if not self._mqtt_available():
            _LOGGER.info(
                "MQTT integration not loaded — skipping topic subscriptions. "
                "Configure MQTT in Home Assistant and reload this integration to enable it."
            )
            self.mqtt_status = "unavailable"
            return

        power_topic: str = self.config.get(CONF_MQTT_POWER_TOPIC, "")
        history_topic: str = self.config.get(CONF_MQTT_HISTORY_TOPIC, "")
        battery_topic: str = self.config.get(CONF_MQTT_BATTERY_TOPIC, "")

        subscribed: list[str] = []

        if power_topic:
            _LOGGER.debug("Subscribing to power topic: %s", power_topic)
            unsub = await mqtt.async_subscribe(
                self.hass, power_topic, self._handle_power_message
            )
            self._mqtt_unsubs.append(unsub)
            subscribed.append(f"power={power_topic}")

        if history_topic:
            _LOGGER.debug("Subscribing to history topic: %s", history_topic)
            unsub = await mqtt.async_subscribe(
                self.hass, history_topic, self._handle_history_message
            )
            self._mqtt_unsubs.append(unsub)
            subscribed.append(f"history={history_topic}")

        if battery_topic:
            _LOGGER.debug("Subscribing to battery topic: %s", battery_topic)
            unsub = await mqtt.async_subscribe(
                self.hass, battery_topic, self._handle_battery_message
            )
            self._mqtt_unsubs.append(unsub)
            subscribed.append(f"battery={battery_topic}")

        if subscribed:
            self.mqtt_status = "connected"
            _LOGGER.info("MQTT subscribed: %s", ", ".join(subscribed))
        else:
            self.mqtt_status = "no_topics"
            _LOGGER.info("MQTT available but no topics configured — UPS control disabled")

    async def async_unload(self) -> None:
        """Cancel all MQTT subscriptions. Call during unload."""
        for unsub in self._mqtt_unsubs:
            unsub()
        self._mqtt_unsubs.clear()

    # ── MQTT message handlers ───────────────────────────────────────────────

    @callback
    def _handle_power_message(self, msg: mqtt.ReceiveMessage) -> None:
        """Parse real-time power draw from MQTT payload (kW)."""
        payload = msg.payload
        try:
            if isinstance(payload, (bytes, bytearray)):
                payload = payload.decode("utf-8")
            payload = payload.strip()
            # Support plain numeric or JSON {"power": 1.5} / {"value": 1.5}
            if payload.startswith("{"):
                data = json.loads(payload)
                value = (
                    data.get("power")
                    or data.get("power_kw")
                    or data.get("value")
                    or data.get("kw")
                    or 0.0
                )
                self.current_power_kw = float(value)
            else:
                self.current_power_kw = float(payload)
            self.mqtt_last_power_update = datetime.now(timezone.utc)
            _LOGGER.debug("Power draw updated: %.3f kW", self.current_power_kw)
            self.async_set_updated_data(self._build_state_snapshot())
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            _LOGGER.warning("Could not parse power MQTT payload %r: %s", payload, exc)

    @callback
    def _handle_history_message(self, msg: mqtt.ReceiveMessage) -> None:
        """Parse historical consumption from MQTT payload (JSON)."""
        payload = msg.payload
        try:
            if isinstance(payload, (bytes, bytearray)):
                payload = payload.decode("utf-8")
            data = json.loads(payload)
            # Expect {"daily": {"YYYY-MM-DD": kWh}, "hourly": {"ISO": kWh}}
            # Fall back gracefully if format differs
            if isinstance(data, dict):
                if "daily" in data or "hourly" in data:
                    self.power_history.update(data)
                else:
                    # Treat as flat hourly dict
                    self.power_history["hourly"].update(data)
            self.mqtt_last_history_update = datetime.now(timezone.utc)
            _LOGGER.debug("Power history updated (%d daily, %d hourly entries)",
                          len(self.power_history.get("daily", {})),
                          len(self.power_history.get("hourly", {})))
            self.async_set_updated_data(self._build_state_snapshot())
        except (json.JSONDecodeError, TypeError) as exc:
            _LOGGER.warning("Could not parse history MQTT payload: %s", exc)

    @callback
    def _handle_battery_message(self, msg: mqtt.ReceiveMessage) -> None:
        """Parse battery level percentage from MQTT payload."""
        payload = msg.payload
        try:
            if isinstance(payload, (bytes, bytearray)):
                payload = payload.decode("utf-8")
            payload = payload.strip()
            if payload.startswith("{"):
                data = json.loads(payload)
                value = (
                    data.get("battery_level")
                    or data.get("soc")
                    or data.get("state_of_charge")
                    or data.get("percent")
                    or data.get("value")
                    or 50.0
                )
                self.battery_level_pct = float(value)
            else:
                self.battery_level_pct = float(payload)
            self.mqtt_last_battery_update = datetime.now(timezone.utc)
            _LOGGER.debug("Battery level updated: %.1f%%", self.battery_level_pct)
            self.async_set_updated_data(self._build_state_snapshot())
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            _LOGGER.warning("Could not parse battery MQTT payload %r: %s", payload, exc)

    # ── DataUpdateCoordinator ───────────────────────────────────────────────

    def _needs_price_refresh(self, now_utc: datetime, now_warsaw: datetime) -> bool:
        """Return True when a Pstryk API call should be made this cycle.

        Three triggers:
        1. First run (no prices yet).
        2. Configured TTL has elapsed since the last successful fetch.
        3. It is past NEXT_DAY_PRICES_HOUR in Warsaw and we have not yet
           captured next-day prices for today's Warsaw date — this ensures
           we pick up tomorrow's TGE prices shortly after they are published,
           even if the regular TTL has not expired yet.
        """
        if self.last_price_refresh is None:
            return True
        if (now_utc - self.last_price_refresh) >= self._price_refresh_interval:
            return True
        # After TGE publication hour: refresh once per Warsaw-calendar-day
        today_warsaw = now_warsaw.date()
        if (
            now_warsaw.hour >= NEXT_DAY_PRICES_HOUR
            and self._next_day_prices_fetched_date != today_warsaw
        ):
            _LOGGER.debug(
                "Triggering next-day price fetch (Warsaw hour=%d, last_fetch_date=%s)",
                now_warsaw.hour, self._next_day_prices_fetched_date,
            )
            return True
        return False

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch prices when needed, regenerate schedule, apply auto-schedule."""
        now_utc = datetime.now(timezone.utc)
        now_warsaw = now_utc.astimezone(self._warsaw)

        if self._needs_price_refresh(now_utc, now_warsaw):
            self.pstryk_api_last_checked = now_utc
            try:
                _LOGGER.debug("Refreshing Pstryk prices")
                prices, includes_next_day = await self._pstryk.async_get_prices()
                self.prices = prices
                self.last_price_refresh = now_utc
                self.pstryk_api_status = "ok"
                self.pstryk_api_last_success = now_utc
                self.pstryk_api_last_error = None

                if includes_next_day:
                    self._next_day_prices_fetched_date = now_warsaw.date()
                    _LOGGER.info(
                        "Fetched %d price records including next-day prices", len(prices)
                    )
                else:
                    _LOGGER.info(
                        "Fetched %d price records (current day only, next-day not yet published)",
                        len(prices),
                    )

                # Regenerate schedule whenever prices change
                await self._refresh_schedule()
            except PstrykAPIError as exc:
                self.pstryk_api_status = "error"
                self.pstryk_api_last_error = str(exc)
                # Don't fail the whole coordinator — continue with stale prices
                if self.prices:
                    _LOGGER.warning("Pstryk API error (using cached prices): %s", exc)
                else:
                    raise UpdateFailed(
                        f"Pstryk API error and no cached prices: {exc}"
                    ) from exc

        # Apply auto-schedule for the current hour
        if self.auto_schedule_enabled and self.schedule:
            self._apply_current_hour_schedule()

        # Recalculate savings estimate
        self._update_savings_estimate()

        return self._build_state_snapshot()

    async def _refresh_schedule(self) -> None:
        """Call Claude (or heuristic fallback) to regenerate the schedule."""
        custom_prompt: str = self.config.get(CONF_CLAUDE_PROMPT, "")
        try:
            self.schedule = await self._planner.async_generate_schedule(
                prices=self.prices,
                current_power_kw=self.current_power_kw,
                power_history=self.power_history,
                current_battery_pct=self.battery_level_pct,
                custom_prompt=custom_prompt,
            )
            _LOGGER.info("Schedule regenerated: %d hours planned", len(self.schedule))
        except Exception as exc:  # noqa: BLE001
            _LOGGER.error("Unexpected error generating schedule: %s", exc, exc_info=True)

        # Sync Claude status from planner attributes (set during generate_schedule)
        self.claude_last_prompt = self._planner.last_prompt
        self.claude_schedule_source = self._planner.last_source
        self.claude_api_last_error = self._planner.last_error
        if self._planner.last_checked:
            if self._planner.last_source == "claude":
                self.claude_api_status = "ok"
                self.claude_api_last_success = self._planner.last_checked
            elif self._planner.last_source == "heuristic" and self._planner.last_error:
                self.claude_api_status = "error"
            # "heuristic" without an error means no prices — not Claude's fault
            elif self._planner.last_source == "heuristic":
                self.claude_api_status = "error"

    def _apply_current_hour_schedule(self) -> None:
        """Set charging/discharging state based on the current hour's scheduled action."""
        now = datetime.now(timezone.utc)
        current_hour_key = now.strftime("%Y-%m-%dT%H:00:00Z")
        for item in self.schedule:
            hour_key = item.get("hour", "")
            if hour_key[:13] == current_hour_key[:13]:
                action = item.get("action", ACTION_IDLE)
                should_charge = action == ACTION_CHARGE
                should_discharge = action == ACTION_DISCHARGE

                if should_charge != self.charging_enabled:
                    _LOGGER.info(
                        "Auto-schedule: charging=%s for hour %s (action=%s, price=%.4f PLN/kWh)",
                        should_charge, hour_key, action, item.get("price_pln_kwh", 0),
                    )
                    self.charging_enabled = should_charge
                    self.hass.async_create_task(self._publish_charge_command(should_charge))

                if should_discharge != self.discharging_enabled:
                    _LOGGER.info(
                        "Auto-schedule: discharging=%s for hour %s (action=%s, price=%.4f PLN/kWh)",
                        should_discharge, hour_key, action, item.get("price_pln_kwh", 0),
                    )
                    self.discharging_enabled = should_discharge
                    self.hass.async_create_task(self._publish_discharge_command(should_discharge))
                break

    def _update_savings_estimate(self) -> None:
        """Estimate PLN saved today vs always-idle baseline."""
        now = datetime.now(timezone.utc)
        today_prefix = now.strftime("%Y-%m-%d")
        capacity_kwh: float = self.config.get(CONF_BATTERY_CAPACITY, 10.0)

        savings = 0.0
        for item in self.schedule:
            hour = item.get("hour", "")
            if not hour.startswith(today_prefix):
                continue
            action = item.get("action", ACTION_IDLE)
            price = item.get("price_pln_kwh", 0.0)
            power_kw = abs(item.get("power_kw", 0.0))
            energy_kwh = power_kw * 1.0  # 1 hour

            if action == ACTION_DISCHARGE:
                # We're selling / offsetting expensive grid energy
                savings += energy_kwh * price
            elif action == ACTION_CHARGE:
                # We're buying cheap energy that we'll use during discharge
                savings -= energy_kwh * price

        self.daily_savings_pln = round(max(0.0, savings), 4)

    def _build_state_snapshot(self) -> dict[str, Any]:
        """Return the coordinator data dict consumed by sensor/switch entities."""
        now = datetime.now(timezone.utc)
        current_price = self._get_current_price()
        current_action = self._get_current_action()
        next_charge = self._get_next_window(ACTION_CHARGE)
        next_discharge = self._get_next_window(ACTION_DISCHARGE)

        return {
            "prices": self.prices,
            "schedule": self.schedule,
            "current_price": current_price,
            "current_action": current_action,
            "current_power_kw": self.current_power_kw,
            "battery_level_pct": self.battery_level_pct,
            "charging_enabled": self.charging_enabled,
            "discharging_enabled": self.discharging_enabled,
            "auto_schedule_enabled": self.auto_schedule_enabled,
            "next_charge_window": next_charge,
            "next_discharge_window": next_discharge,
            "daily_savings_pln": self.daily_savings_pln,
            "last_price_refresh": (
                self.last_price_refresh.isoformat() if self.last_price_refresh else None
            ),
            # Indicates whether tomorrow's prices are included in the current dataset.
            # False before ~15:00 Warsaw; True once TGE publishes next-day prices.
            "next_day_prices_available": self._next_day_prices_fetched_date == now.astimezone(self._warsaw).date(),
            # Pstryk API status
            "pstryk_api_status": self.pstryk_api_status,
            "pstryk_api_last_error": self.pstryk_api_last_error,
            "pstryk_api_last_success": (
                self.pstryk_api_last_success.isoformat() if self.pstryk_api_last_success else None
            ),
            "pstryk_api_last_checked": (
                self.pstryk_api_last_checked.isoformat() if self.pstryk_api_last_checked else None
            ),
            # Claude API status
            "claude_api_status": self.claude_api_status,
            "claude_api_last_error": self.claude_api_last_error,
            "claude_api_last_success": (
                self.claude_api_last_success.isoformat() if self.claude_api_last_success else None
            ),
            "claude_schedule_source": self.claude_schedule_source,
            "claude_last_prompt": self.claude_last_prompt,
            # MQTT status
            "mqtt_status": self.mqtt_status,
            "mqtt_last_power_update": (
                self.mqtt_last_power_update.isoformat() if self.mqtt_last_power_update else None
            ),
            "mqtt_last_history_update": (
                self.mqtt_last_history_update.isoformat() if self.mqtt_last_history_update else None
            ),
            "mqtt_last_battery_update": (
                self.mqtt_last_battery_update.isoformat() if self.mqtt_last_battery_update else None
            ),
            "mqtt_power_topic": self.config.get(CONF_MQTT_POWER_TOPIC, ""),
            "mqtt_history_topic": self.config.get(CONF_MQTT_HISTORY_TOPIC, ""),
            "mqtt_charge_topic": self.config.get(CONF_MQTT_CHARGE_TOPIC, ""),
            "mqtt_discharge_topic": self.config.get(CONF_MQTT_DISCHARGE_TOPIC, ""),
            "mqtt_battery_topic": self.config.get(CONF_MQTT_BATTERY_TOPIC, ""),
        }

    # ── Price & schedule helpers ────────────────────────────────────────────

    def _get_current_price(self) -> float | None:
        """Return the electricity price for the current hour, or None."""
        now = datetime.now(timezone.utc)
        current_hour_key = now.strftime("%Y-%m-%dT%H:00:00Z")
        for p in self.prices:
            ts = p.get("timestamp", "")
            if ts[:13] == current_hour_key[:13]:
                return p.get("price")
        return None

    def _get_current_action(self) -> str:
        """Return the scheduled action for the current hour."""
        now = datetime.now(timezone.utc)
        current_hour_key = now.strftime("%Y-%m-%dT%H:00:00Z")
        for item in self.schedule:
            if item.get("hour", "")[:13] == current_hour_key[:13]:
                return item.get("action", ACTION_IDLE)
        return ACTION_IDLE

    def _get_next_window(self, action: str) -> str | None:
        """Return the ISO timestamp of the next upcoming window for *action*."""
        now = datetime.now(timezone.utc)
        for item in self.schedule:
            if item.get("action") != action:
                continue
            ts_str = item.get("hour", "")
            try:
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                if ts > now:
                    return ts_str
            except ValueError:
                pass
        return None

    # ── Public control methods ──────────────────────────────────────────────

    async def set_charging(self, enabled: bool) -> None:
        """Enable or disable UPS charging and publish to MQTT charge topic."""
        self.charging_enabled = enabled
        await self._publish_charge_command(enabled)
        self.async_update_listeners()

    async def set_discharging(self, enabled: bool) -> None:
        """Enable or disable UPS discharging and publish to MQTT discharge topic."""
        self.discharging_enabled = enabled
        await self._publish_discharge_command(enabled)
        self.async_update_listeners()

    async def set_auto_schedule(self, enabled: bool) -> None:
        """Enable or disable automatic schedule following."""
        self.auto_schedule_enabled = enabled
        _LOGGER.info("Auto-schedule %s", "enabled" if enabled else "disabled")
        if enabled:
            self._apply_current_hour_schedule()
        self.async_update_listeners()

    async def _publish_charge_command(self, enabled: bool) -> None:
        """Publish 1 (on) or 0 (off) to the configured MQTT charge topic."""
        topic: str = self.config.get(CONF_MQTT_CHARGE_TOPIC, "")
        if not topic or not self._mqtt_available():
            _LOGGER.debug("Charge publish skipped (topic=%r, mqtt=%s)", topic, self.mqtt_status)
            return
        payload = MQTT_PAYLOAD_ON if enabled else MQTT_PAYLOAD_OFF
        try:
            await mqtt.async_publish(self.hass, topic, payload, qos=1, retain=True)
            _LOGGER.debug("Charge command: published '%s' to %s", payload, topic)
        except Exception as exc:  # noqa: BLE001
            _LOGGER.error("Failed to publish charge command: %s", exc)

    async def _publish_discharge_command(self, enabled: bool) -> None:
        """Publish 1 (on) or 0 (off) to the configured MQTT discharge topic."""
        topic: str = self.config.get(CONF_MQTT_DISCHARGE_TOPIC, "")
        if not topic or not self._mqtt_available():
            _LOGGER.debug("Discharge publish skipped (topic=%r, mqtt=%s)", topic, self.mqtt_status)
            return
        payload = MQTT_PAYLOAD_ON if enabled else MQTT_PAYLOAD_OFF
        try:
            await mqtt.async_publish(self.hass, topic, payload, qos=1, retain=True)
            _LOGGER.debug("Discharge command: published '%s' to %s", payload, topic)
        except Exception as exc:  # noqa: BLE001
            _LOGGER.error("Failed to publish discharge command: %s", exc)
