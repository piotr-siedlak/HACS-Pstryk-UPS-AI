# Pstryk UPS AI Optimizer

A production-ready [Home Assistant](https://www.home-assistant.io/) custom integration installable via [HACS](https://hacs.xyz/) that automatically optimises UPS battery charging and discharging cycles based on real-time electricity prices from the **Pstryk API** and AI-powered scheduling via **Claude (Anthropic)**.

---

## Features

- **Full electricity price** — fetches `total_cost` (energy + distribution + fees + taxes) from the Pstryk API, so scheduling decisions reflect what you actually pay
- **Current-day and next-day prices** — after ~15:00 Warsaw time, next-day TGE prices are automatically included so Claude can optimise across midnight
- **AI schedule planning** — sends prices, household consumption history, and battery constraints to Claude, which returns a 24-hour hourly charge/discharge plan optimised to minimise cost
- **Heuristic fallback** — if Claude is unavailable, a deterministic algorithm charges during the cheapest hours and discharges during the most expensive, respecting battery min/max at all times
- **Configurable battery constraints** — set minimum (reserve) and maximum charge % passed directly to Claude for realistic planning
- **MQTT integration** — subscribes to configurable topics for real-time power draw, historical consumption, and battery state of charge; publishes `1`/`0` commands to separate charge and discharge control topics
- **API status monitoring** — dedicated sensors show whether the Pstryk and Claude APIs are reachable, with last-success timestamp, last error message, and schedule source (claude/heuristic)
- **9 sensor entities** — electricity price, power draw, schedule status, next charge/discharge windows, battery level, daily savings estimate, Pstryk API status, Claude API status
- **3 switch entities** — manual charging toggle, manual discharging toggle, auto-schedule enable/disable
- **Single-page Configure panel** — update all UPS parameters and MQTT topics together on one screen via the **Configure** button, no need to remove the integration
- **Reconfigure support** — update API keys independently without touching UPS or MQTT settings
- **English and Polish translations**

---

## Requirements

| Requirement | Details |
|---|---|
| Home Assistant | 2024.1.0 or newer |
| HACS | 1.31.0 or newer |
| Python package | `anthropic>=0.40.0` (installed automatically) |
| HA integration | MQTT (built-in, must be configured) |
| API keys | Pstryk API token + Anthropic API key |

---

## Installation via HACS

1. Open **HACS** in Home Assistant.
2. Click **Custom Repositories** (⋮ menu) and add:
   - **URL**: `https://github.com/piotr-siedlak/hacs-pstryk-ups-ai`
   - **Category**: Integration
3. Click **Add**, then find **Pstryk UPS AI Optimizer** in the integration list and click **Download**.
4. Restart Home Assistant.

### Manual installation

1. Copy the `custom_components/pstryk_ups/` directory into your HA `config/custom_components/` directory.
2. Restart Home Assistant.

---

## Configuration

### Prerequisites

- **Pstryk API key** — obtain from the [Pstryk customer portal](https://pstryk.pl).
- **Anthropic API key** — obtain from [console.anthropic.com](https://console.anthropic.com/).
- **MQTT broker** configured in Home Assistant (Settings → Devices & Services → MQTT).

### Adding the integration

1. Go to **Settings → Devices & Services → Add Integration**.
2. Search for **Pstryk UPS AI Optimizer**.
3. Complete the three-step config flow:

#### Step 1 — API Keys

| Field | Description |
|---|---|
| Pstryk API Key | Your Pstryk electricity pricing API token |
| Claude (Anthropic) API Key | Your Anthropic API key |

Both keys are validated against their respective APIs before proceeding.

#### Step 2 — UPS Parameters

| Field | Default | Description |
|---|---|---|
| UPS Model Name | Generic UPS | Display name (e.g. `SolarEdge 10kWh`) |
| Total Battery Capacity | 10.0 kWh | Usable capacity across all strings |
| Number of Battery Strings | 1 | Parallel battery strings in your system |
| Maximum Charge Rate | 2.0 kW | Max power at which the UPS can charge |
| Maximum Discharge Rate | 2.0 kW | Max power the UPS can supply from battery |
| Minimum Battery Level | 10 % | Never discharge below this level — sent to Claude as a hard constraint |
| Maximum Battery Level | 90 % | Never charge above this level — sent to Claude as a hard constraint |

#### Step 3 — MQTT Topics & Scheduling

| Field | Description |
|---|---|
| Real-time Power Topic | MQTT topic publishing household power draw in kW |
| Historical Consumption Topic | MQTT topic publishing JSON consumption history |
| UPS Charge Control Topic | MQTT topic that receives `1`/`0` charge commands |
| UPS Discharge Control Topic | MQTT topic that receives `1`/`0` discharge commands |
| Battery Level Topic | MQTT topic publishing battery state of charge in % |
| Price Refresh Interval | How often (in hours) to fetch new prices from Pstryk (default: 6) |

All fields are required.

### Changing settings after setup

Go to **Settings → Devices & Services → Pstryk UPS AI Optimizer → Configure** to update all UPS parameters and MQTT topics on a single page. Changes take effect immediately after saving.

To update API keys, use the **Reconfigure** option from the integration's three-dot (⋮) menu.

---

## MQTT Payload Formats

### Power topic (subscribe)

Plain numeric:
```
1.85
```
Or JSON:
```json
{"power": 1.85}
```
```json
{"power_kw": 1.85}
```

### Historical consumption topic (subscribe)

```json
{
  "daily": {
    "2024-01-14": 18.5,
    "2024-01-13": 21.2
  },
  "hourly": {
    "2024-01-14T08:00:00Z": 2.1,
    "2024-01-14T09:00:00Z": 1.8
  }
}
```

### Battery level topic (subscribe)

Plain numeric:
```
75.5
```
Or JSON:
```json
{"soc": 75.5}
```
```json
{"battery_level": 75.5}
```

### Charge control topic (publish)

The integration publishes `1` (enable) or `0` (disable) — retained, QoS 1 — whenever:
- The auto-schedule activates or deactivates charging for the current hour
- The user toggles the **UPS Charging** switch manually

### Discharge control topic (publish)

The integration publishes `1` (enable) or `0` (disable) — retained, QoS 1 — whenever:
- The auto-schedule activates or deactivates discharging for the current hour
- The user toggles the **UPS Discharging** switch manually

---

## Entities

### Sensors

| Entity ID | Description | Unit | Key Attributes |
|---|---|---|---|
| `sensor.pstryk_ups_electricity_price` | Current total electricity price (incl. distribution + taxes) | PLN/kWh | `upcoming_prices`, `last_refresh`, `price_count` |
| `sensor.pstryk_ups_household_power_draw` | Live household power draw from MQTT | kW | `history_daily_entries`, `history_hourly_entries` |
| `sensor.pstryk_ups_schedule_status` | Current scheduled action | charge / discharge / idle | `schedule` (full 24-h list), `schedule_hours`, `auto_schedule_enabled` |
| `sensor.pstryk_ups_next_charge_window` | Start of the next planned charging window | timestamp | `charge_windows` |
| `sensor.pstryk_ups_next_discharge_window` | Start of the next planned discharge window | timestamp | `discharge_windows` |
| `sensor.pstryk_ups_battery_level` | Battery state of charge from MQTT | % | `projected_end_level_pct` |
| `sensor.pstryk_ups_estimated_daily_savings` | Estimated PLN saved today vs always-idle | PLN | `scheduled_charge_hours`, `scheduled_discharge_hours` |
| `sensor.pstryk_ups_pstryk_api_status` | Pstryk API reachability | ok / error / unknown | `last_success`, `last_error`, `last_checked`, `next_day_prices_available` |
| `sensor.pstryk_ups_claude_api_status` | Claude AI API status and schedule source | ok / error / unknown | `last_success`, `last_error`, `schedule_source` (claude / heuristic) |

### Switches

| Entity ID | Description |
|---|---|
| `switch.pstryk_ups_ups_charging` | Enable/disable UPS charging — publishes `1`/`0` to the charge control topic |
| `switch.pstryk_ups_ups_discharging` | Enable/disable UPS discharging — publishes `1`/`0` to the discharge control topic |
| `switch.pstryk_ups_auto_schedule` | Enable/disable AI-driven automatic scheduling |

---

## How the AI Scheduling Works

1. Every hour the coordinator checks whether prices need refreshing based on the configured interval.
2. Prices fetched from Pstryk use the `total_cost` field — the full amount you pay per kWh including energy, distribution, and all taxes. This ensures scheduling decisions match your actual bill.
3. Current-day prices are always available. After ~15:00 Warsaw time the window is automatically extended to include next-day TGE prices, so Claude can optimise overnight cycles.
4. When fresh prices arrive, they are sent to Claude along with:
   - Your UPS configuration (capacity, charge/discharge rates, min/max battery %)
   - Current household power draw (from MQTT)
   - Historical consumption data from MQTT (past 7 days)
   - Current battery state of charge
5. Claude returns a 24-hour schedule with hourly actions (`charge`, `discharge`, `idle`), planned power (kW), price context, reason, and projected battery level.
6. If Claude fails (API error, network issue, unparseable response), the integration automatically falls back to a heuristic:
   - Charge during the cheapest upcoming hours
   - Discharge during the most expensive upcoming hours
   - Battery min/max % constraints always respected
7. The `sensor.pstryk_ups_claude_api_status` sensor shows whether Claude or the heuristic generated the current schedule, and exposes any error message in its attributes.
8. When **Auto Schedule** is ON, both charging and discharging switches update automatically each hour to follow the plan.
9. You can override at any time by toggling the switches manually — overrides last until the next hourly update when auto-schedule re-applies.

---

## Dashboard Example

Add a Lovelace **Entities** card:

```yaml
type: entities
title: UPS AI Optimizer
entities:
  - entity: switch.pstryk_ups_auto_schedule
  - entity: switch.pstryk_ups_ups_charging
  - entity: switch.pstryk_ups_ups_discharging
  - entity: sensor.pstryk_ups_electricity_price
  - entity: sensor.pstryk_ups_schedule_status
  - entity: sensor.pstryk_ups_battery_level
  - entity: sensor.pstryk_ups_next_charge_window
  - entity: sensor.pstryk_ups_next_discharge_window
  - entity: sensor.pstryk_ups_estimated_daily_savings
  - entity: sensor.pstryk_ups_pstryk_api_status
  - entity: sensor.pstryk_ups_claude_api_status
```

To show the full 24-hour schedule, use a **Markdown** card:

```yaml
type: markdown
content: >
  {% set schedule = state_attr('sensor.pstryk_ups_schedule_status', 'schedule') %}
  {% if schedule %}
  | Hour (UTC) | Action | Price PLN/kWh | Power kW | Reason |
  |---|---|---|---|---|
  {% for item in schedule %}
  | {{ item.hour[11:16] }} | {{ item.action }} | {{ item.price_pln_kwh }} | {{ item.power_kw }} | {{ item.reason }} |
  {% endfor %}
  {% else %}
  No schedule available yet.
  {% endif %}
```

---

## Troubleshooting

| Problem | Solution |
|---|---|
| Integration won't set up — "Cannot connect" | Check your network and that `api.pstryk.pl` is reachable |
| "Invalid Pstryk API key" | Verify the token in the Pstryk customer portal; the key is sent as a raw `Authorization` header (no "Token" prefix) |
| "Invalid Claude API key" | Verify the key at console.anthropic.com and check your usage limits |
| Electricity price shows 0 or wrong value | Check `sensor.pstryk_ups_pstryk_api_status` attributes for `last_error`; the integration uses `total_cost` field from the API |
| Claude status shows "error" | Check `sensor.pstryk_ups_claude_api_status` → `last_error` attribute; the heuristic fallback is active |
| Schedule source shows "heuristic" | Claude API returned an error — check your Anthropic API key and credit balance |
| No MQTT data arriving | Ensure the MQTT broker is running and the configured topics are publishing |
| Schedule shows all "idle" | Claude returned an empty or unparseable schedule; check HA logs for details |
| Battery level stuck at 50% | Verify your device is publishing to the configured battery MQTT topic |
| UPS not charging/discharging | Verify your device subscribes to the correct MQTT topics and responds to `1`/`0` payloads |
| MQTT topics missing from Configure panel | All UPS and MQTT settings appear together on a single Configure page — scroll down if needed |

Enable debug logging for detailed diagnostics:

```yaml
# configuration.yaml
logger:
  logs:
    custom_components.pstryk_ups: debug
```

---

## Changelog

### v1.5.0
- **Price field**: Changed to `total_cost` as the primary price field — includes energy, distribution, fees, and taxes — so scheduling reflects the actual price you pay, not just the raw TGE spot price

### v1.4.0
- **API status sensors**: Added `sensor.pstryk_ups_pstryk_api_status` and `sensor.pstryk_ups_claude_api_status` with last-success timestamp, last error message, and schedule source (claude/heuristic) in attributes
- **Single-page Configure panel**: Merged UPS parameters and MQTT topics into one page — previously MQTT settings were inaccessible from the Configure button
- **Discharging switch**: Added `switch.pstryk_ups_ups_discharging` for manual and auto-schedule controlled discharge
- **Battery topic required**: Battery MQTT topic is now required (was incorrectly marked optional)

### v1.3.0
- **Auth header fix**: Removed erroneous `Token` prefix from the Pstryk API `Authorization` header — raw key is correct per the Pstryk API spec
- **API parameter fix**: Removed `for_tz` parameter which is not allowed with `resolution=hour` per the Pstryk API documentation

---

## Contributing

Bug reports and pull requests are welcome at [github.com/piotr-siedlak/hacs-pstryk-ups-ai](https://github.com/piotr-siedlak/hacs-pstryk-ups-ai).

---

## License

MIT License — see `LICENSE` for details.
