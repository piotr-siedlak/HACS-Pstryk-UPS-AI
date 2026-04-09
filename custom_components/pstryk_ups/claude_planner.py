"""Claude AI planning engine for UPS charge/discharge scheduling."""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

import anthropic

from .const import (
    ACTION_CHARGE,
    ACTION_DISCHARGE,
    ACTION_IDLE,
    CLAUDE_MAX_TOKENS,
    CLAUDE_MODEL,
    DEFAULT_BATTERY_MAX_PCT,
    DEFAULT_BATTERY_MIN_PCT,
    HEURISTIC_CHARGE_HOURS,
    HEURISTIC_DISCHARGE_HOURS,
)

_LOGGER = logging.getLogger(__name__)


class ClaudePlannerError(Exception):
    """Raised when Claude cannot produce a valid schedule."""


class ClaudePlanner:
    """Use Claude to generate an optimised UPS charge/discharge schedule.

    If Claude is unavailable or returns an unparseable response, the planner
    falls back to a deterministic heuristic: charge during the cheapest
    ``HEURISTIC_CHARGE_HOURS`` hours and discharge during the most expensive
    ``HEURISTIC_DISCHARGE_HOURS`` hours within the upcoming 24-hour window.
    """

    def __init__(self, api_key: str, ups_config: dict[str, Any]) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._ups_config = ups_config  # keys: battery_capacity_kwh, max_charge_rate_kw,
        #        max_discharge_rate_kw, num_strings, ups_model

        # Status tracking — read by coordinator for the Claude API status sensor
        self.last_source: str = "unknown"   # "claude" | "heuristic" | "unknown"
        self.last_error: str | None = None
        self.last_checked: datetime | None = None

    # ── Public API ──────────────────────────────────────────────────────────

    async def async_generate_schedule(
        self,
        prices: list[dict[str, Any]],
        current_power_kw: float,
        power_history: dict[str, Any],
        current_battery_pct: float = 50.0,
    ) -> list[dict[str, Any]]:
        """Return a 24-hour charge/discharge schedule.

        Each item in the returned list is a dict with:
        - ``hour``            – ISO-8601 UTC timestamp (start of the hour)
        - ``action``          – "charge" | "discharge" | "idle"
        - ``price_pln_kwh``   – electricity price for that hour (PLN/kWh)
        - ``power_kw``        – planned power (positive = charging, negative = discharging)
        - ``reason``          – human-readable explanation
        - ``battery_level_pct`` – estimated battery SOC at end of this hour (%)
        """
        self.last_checked = datetime.now(timezone.utc)

        if not prices:
            _LOGGER.warning("No price data available; using heuristic schedule")
            self.last_source = "heuristic"
            self.last_error = "No price data available"
            return self._heuristic_schedule(prices, current_battery_pct)

        try:
            prompt = self._build_prompt(prices, current_power_kw, power_history, current_battery_pct)
            _LOGGER.debug("Requesting schedule from Claude (%s)", CLAUDE_MODEL)
            message = await self._client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=CLAUDE_MAX_TOKENS,
                messages=[{"role": "user", "content": prompt}],
            )
            raw_text = message.content[0].text
            schedule = self._parse_schedule(raw_text, prices)
            if not schedule:
                raise ClaudePlannerError("Claude returned an empty or invalid schedule")
            _LOGGER.debug("Claude returned %d schedule items", len(schedule))
            self.last_source = "claude"
            self.last_error = None
            return schedule
        except anthropic.APIError as exc:
            _LOGGER.error("Claude API error: %s — falling back to heuristic schedule", exc)
            self.last_source = "heuristic"
            self.last_error = str(exc)
        except ClaudePlannerError as exc:
            _LOGGER.warning("Schedule parsing failed: %s — falling back to heuristic schedule", exc)
            self.last_source = "heuristic"
            self.last_error = str(exc)

        return self._heuristic_schedule(prices, current_battery_pct)

    async def async_validate_key(self) -> bool:
        """Return True when the Claude API key is accepted."""
        try:
            await self._client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=10,
                messages=[{"role": "user", "content": "ping"}],
            )
            return True
        except anthropic.AuthenticationError:
            return False
        except anthropic.APIError as exc:
            _LOGGER.warning("Claude key validation non-auth error: %s", exc)
            return True  # ambiguous — allow save, fail loudly at runtime

    # ── Prompt construction ─────────────────────────────────────────────────

    def _build_prompt(
        self,
        prices: list[dict[str, Any]],
        current_power_kw: float,
        power_history: dict[str, Any],
        current_battery_pct: float,
    ) -> str:
        cfg = self._ups_config
        capacity_kwh: float = cfg.get("battery_capacity_kwh", 10.0)
        max_charge: float = cfg.get("max_charge_rate_kw", 2.0)
        max_discharge: float = cfg.get("max_discharge_rate_kw", 2.0)
        num_strings: int = cfg.get("num_strings", 1)
        ups_model: str = cfg.get("ups_model", "Generic UPS")
        battery_min_pct: float = cfg.get("battery_min_pct", DEFAULT_BATTERY_MIN_PCT)
        battery_max_pct: float = cfg.get("battery_max_pct", DEFAULT_BATTERY_MAX_PCT)

        # Limit price table to next 48 h for prompt size
        price_table = "\n".join(
            f"  {p['timestamp']}  {p['price']:.4f} PLN/kWh"
            for p in prices[:48]
        )

        # Summarise history for prompt (keep it compact)
        history_summary = json.dumps(power_history, indent=2, default=str)[:2000]

        return f"""You are an expert energy management AI optimising a home UPS system.

## UPS Configuration
- Model: {ups_model}
- Battery capacity: {capacity_kwh} kWh
- Number of battery strings: {num_strings}
- Maximum charge rate: {max_charge} kW
- Maximum discharge rate: {max_discharge} kW
- Current battery level: {current_battery_pct:.1f}%
- Minimum battery reserve (never discharge below): {battery_min_pct:.1f}%
- Maximum charge level (never charge above): {battery_max_pct:.1f}%

## Electricity Price Forecast (PLN/kWh, hourly, UTC timestamps)
{price_table}

## Current Household Power Draw
{current_power_kw:.2f} kW

## Historical Consumption (past 7 days)
{history_summary}

## Task
Generate an optimised UPS charge/discharge schedule for the next 24 hours starting NOW.

Optimisation rules:
1. CHARGE during the cheapest hours (below the 24-h average price ideally).
2. DISCHARGE during the most expensive hours (above average + margin).
3. Never let the battery drop below {battery_min_pct:.1f}% (minimum reserve).
4. Never charge the battery above {battery_max_pct:.1f}% (maximum charge level).
5. Respect maximum charge/discharge rates.
6. Consider typical household consumption to avoid over-discharging.
7. If the price spread is too small (<15% between cheap and expensive), prefer IDLE.
8. Account for charging/discharging efficiency (~90%).

Return ONLY a valid JSON array — no prose, no markdown, no code fences — with exactly one object per hour for the next 24 hours:

[
  {{
    "hour": "2024-01-15T08:00:00Z",
    "action": "charge",
    "price_pln_kwh": 0.4500,
    "power_kw": 2.0,
    "reason": "Lowest price window – 40% below 24-h average",
    "battery_level_pct": 62.5
  }},
  ...
]

Constraints on the JSON:
- "action" must be exactly one of: "charge", "discharge", "idle"
- "power_kw" is positive for charging, negative for discharging, 0 for idle
- "battery_level_pct" must stay within [{battery_min_pct:.1f}, {battery_max_pct:.1f}]
- Include all 24 hours; if no action is optimal, use "idle"
"""

    # ── Response parsing ────────────────────────────────────────────────────

    def _parse_schedule(
        self,
        text: str,
        prices: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Extract and validate the JSON schedule from Claude's response."""
        # Strip markdown code fences if Claude added them
        text = re.sub(r"```(?:json)?", "", text, flags=re.IGNORECASE).strip()

        # Find the outermost JSON array
        match = re.search(r"\[.*\]", text, re.DOTALL)
        if not match:
            raise ClaudePlannerError("No JSON array found in Claude response")

        try:
            raw: list[Any] = json.loads(match.group())
        except json.JSONDecodeError as exc:
            raise ClaudePlannerError(f"JSON decode error: {exc}") from exc

        if not isinstance(raw, list) or len(raw) == 0:
            raise ClaudePlannerError("Parsed schedule is empty or not a list")

        schedule: list[dict[str, Any]] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            action = str(item.get("action", ACTION_IDLE)).lower()
            if action not in (ACTION_CHARGE, ACTION_DISCHARGE, ACTION_IDLE):
                action = ACTION_IDLE

            try:
                power_kw = float(item.get("power_kw", 0.0))
                price = float(item.get("price_pln_kwh", 0.0))
                battery_pct = float(item.get("battery_level_pct", 50.0))
                battery_pct = max(0.0, min(100.0, battery_pct))
            except (TypeError, ValueError):
                power_kw, price, battery_pct = 0.0, 0.0, 50.0

            schedule.append(
                {
                    "hour": str(item.get("hour", "")),
                    "action": action,
                    "price_pln_kwh": price,
                    "power_kw": power_kw,
                    "reason": str(item.get("reason", "")),
                    "battery_level_pct": battery_pct,
                }
            )

        return schedule

    # ── Heuristic fallback ──────────────────────────────────────────────────

    def _heuristic_schedule(
        self,
        prices: list[dict[str, Any]],
        current_battery_pct: float,
    ) -> list[dict[str, Any]]:
        """Simple price-rank-based schedule used when Claude is unavailable."""
        now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        capacity_kwh: float = self._ups_config.get("battery_capacity_kwh", 10.0)
        max_charge: float = self._ups_config.get("max_charge_rate_kw", 2.0)
        max_discharge: float = self._ups_config.get("max_discharge_rate_kw", 2.0)
        battery_min_pct: float = self._ups_config.get("battery_min_pct", DEFAULT_BATTERY_MIN_PCT)
        battery_max_pct: float = self._ups_config.get("battery_max_pct", DEFAULT_BATTERY_MAX_PCT)

        # Build a price lookup for the next 24 h
        price_by_hour: dict[str, float] = {}
        for p in prices:
            ts = p.get("timestamp", "")
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                price_by_hour[dt.strftime("%Y-%m-%dT%H:00:00Z")] = p.get("price", 0.0)
            except ValueError:
                pass

        hours = [
            (now + timedelta(hours=i)).strftime("%Y-%m-%dT%H:00:00Z")
            for i in range(24)
        ]

        if not price_by_hour:
            # No price data at all – return all-idle schedule
            return [
                {
                    "hour": h,
                    "action": ACTION_IDLE,
                    "price_pln_kwh": 0.0,
                    "power_kw": 0.0,
                    "reason": "No price data available",
                    "battery_level_pct": current_battery_pct,
                }
                for h in hours
            ]

        prices_for_hours = [(h, price_by_hour.get(h, 0.0)) for h in hours]
        sorted_asc = sorted(prices_for_hours, key=lambda x: x[1])
        sorted_desc = sorted(prices_for_hours, key=lambda x: x[1], reverse=True)

        charge_hours = {h for h, _ in sorted_asc[:HEURISTIC_CHARGE_HOURS]}
        discharge_hours = {h for h, _ in sorted_desc[:HEURISTIC_DISCHARGE_HOURS]}

        battery_pct = current_battery_pct
        schedule: list[dict[str, Any]] = []

        for hour, price in prices_for_hours:
            if hour in charge_hours and battery_pct < battery_max_pct:
                action = ACTION_CHARGE
                power_kw = max_charge
                delta_pct = (power_kw / capacity_kwh) * 100.0
                battery_pct = min(battery_max_pct, battery_pct + delta_pct)
                reason = "Heuristic: low-price charging window"
            elif hour in discharge_hours and battery_pct > battery_min_pct:
                action = ACTION_DISCHARGE
                power_kw = -max_discharge
                delta_pct = (max_discharge / capacity_kwh) * 100.0
                battery_pct = max(battery_min_pct, battery_pct - delta_pct)
                reason = "Heuristic: high-price discharge window"
            else:
                action = ACTION_IDLE
                power_kw = 0.0
                reason = "Heuristic: idle"

            schedule.append(
                {
                    "hour": hour,
                    "action": action,
                    "price_pln_kwh": price,
                    "power_kw": power_kw,
                    "reason": reason,
                    "battery_level_pct": round(battery_pct, 1),
                }
            )

        return schedule
