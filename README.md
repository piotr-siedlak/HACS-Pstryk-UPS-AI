# Pstryk UPS AI Optimizer

A production-ready [Home Assistant](https://www.home-assistant.io/) custom integration installable via [HACS](https://hacs.xyz/) that automatically optimises UPS battery charging and discharging cycles based on real-time electricity prices from the **Pstryk API** and AI-powered scheduling via **Claude (Anthropic)**.

---

## Features

- **Live electricity prices** — fetches current-day and (after ~15:00 Warsaw time) next-day TGE spot prices from the Pstryk API at a configurable interval
- **AI schedule planning** — sends prices + household consumption history + battery constraints to Claude, which returns an hourly charge/discharge plan optimised to minimise energy costs
- **Heuristic fallback** — if Claude is unavailable the integration falls back to a deterministic algorithm (charge in cheapest N hours, discharge in most expensive N hours), respecting the configured battery min/max
- **Configurable battery constraints** — set minimum (reserve) and maximum charge % passed to Claude for realistic planning
- **MQTT integration** — subscribes to configurable topics for:
  - Real-time household power draw (kW)
  - Historical consumption data (kWh/day, kWh/hour)
  - Optional UPS battery state of charge (%)
  - Publishes `1`/`0` commands to separate UPS charge and discharge control topics
- **7 sensor entities** — electricity price, power draw, schedule status, next charge/discharge windows, battery level, daily savings estimate
- **3 switch entities** — manual charging toggle, manual discharging toggle, and auto-schedule enable/disable
- **Full config flow** — all settings configurable via the Home Assistant UI (no YAML required)
- **Options flow** — update UPS parameters and MQTT topics at any time via the **Configure** button without removing the integration
- **Reconfigure support** — update API keys without removing the integration
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
| Claude API Key | Your Anthropic API key |

Both keys are validated before proceeding.

#### Step 2 — UPS Parameters

| Field | Default | Description |
|---|---|---|
| UPS Model Name | Generic UPS | Display name (e.g. `SolarEdge 10kWh`) |
| Total Battery Capacity | 10.0 kWh | Usable capacity across all strings |
| Number of Battery Strings | 1 | Parallel battery strings |
| Maximum Charge Rate | 2.0 kW | Max charging power |
| Maximum Discharge Rate | 2.0 kW | Max discharging power |
| Minimum Battery Level | 10 % | Never discharge below this level (sent to Claude) |
| Maximum Battery Level | 90 % | Never charge above this level (sent to Claude) |

#### Step 3 — MQTT Topics & Scheduling

| Field | Required | Description |
|---|---|---|
| Real-time Power Topic | Yes | MQTT topic publishing household power draw in kW |
| Historical Consumption Topic | Yes | MQTT topic publishing JSON consumption history |
| UPS Charge Control Topic | Yes | MQTT topic to receive `1`/`0` charge commands |
| UPS Discharge Control Topic | Yes | MQTT topic to receive `1`/`0` discharge commands |
| Battery Level Topic | No | MQTT topic publishing battery % (improves estimates) |
| Price Refresh Interval | Yes (default 6) | How often (hours) to call the Pstryk API |

### Changing settings after setup

Go to **Settings → Devices & Services → Pstryk UPS AI Optimizer → Configure** to update:
- UPS parameters (capacity, rates, battery min/max)
- MQTT topics and price refresh interval

To update API keys, use the **Reconfigure** option from the integration's three-dot menu.

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

### Battery level topic (subscribe, optional)

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

The integration publishes `1` (enable) or `0` (disable) — retained, QoS 1 — to the configured charge topic whenever:
- The auto-schedule activates or deactivates charging
- The user toggles the **UPS Charging** switch in HA

### Discharge control topic (publish)

The integration publishes `1` (enable) or `0` (disable) — retained, QoS 1 — to the configured discharge topic whenever:
- The auto-schedule activates or deactivates discharging
- The user toggles the **UPS Discharging** switch in HA

---

## Entities

### Sensors

| Entity ID | Description | Unit |
|---|---|---|
| `sensor.pstryk_ups_electricity_price` | Current electricity price | PLN/kWh |
| `sensor.pstryk_ups_household_power_draw` | Live household power (MQTT) | kW |
| `sensor.pstryk_ups_schedule_status` | Current schedule action | charge/discharge/idle |
| `sensor.pstryk_ups_next_charge_window` | Next planned charging start | timestamp |
| `sensor.pstryk_ups_next_discharge_window` | Next planned discharge start | timestamp |
| `sensor.pstryk_ups_battery_level` | Battery state of charge | % |
| `sensor.pstryk_ups_estimated_daily_savings` | Estimated PLN saved today | PLN |

### Switches

| Entity ID | Description |
|---|---|
| `switch.pstryk_ups_ups_charging` | Enable/disable UPS charging (publishes `1`/`0` to charge topic) |
| `switch.pstryk_ups_ups_discharging` | Enable/disable UPS discharging (publishes `1`/`0` to discharge topic) |
| `switch.pstryk_ups_auto_schedule` | Enable/disable AI automatic scheduling |

---

## How the AI Scheduling Works

1. Every hour the coordinator checks whether prices need refreshing (based on your configured interval).
2. Current-day prices are always available. After ~15:00 Warsaw time the integration automatically extends the fetch window to include next-day prices, so Claude can optimise across midnight.
3. When fresh prices are available, they are sent to Claude along with:
   - Your UPS configuration (capacity, charge/discharge rates, min/max battery %)
   - Current household power draw
   - Historical consumption data (past 7 days)
   - Current battery state of charge
4. Claude returns a 24-hour schedule with hourly actions (`charge`, `discharge`, `idle`), planned power, price context, and projected battery level.
5. If Claude fails (API error, network issue, invalid response), the integration automatically falls back to a heuristic:
   - Charge during the cheapest upcoming hours
   - Discharge during the most expensive upcoming hours
   - Respect the configured battery min/max % at all times
6. When **Auto Schedule** is ON, both the charging and discharging switch states are automatically updated each hour to follow the plan.
7. You can override at any time by toggling the **UPS Charging** or **UPS Discharging** switches — the override lasts until the next hourly update.

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
```

To show the full 24-hour schedule, use a **Markdown** card with a template:

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
| "Invalid Pstryk API key" | Verify the token in the Pstryk customer portal |
| "Invalid Claude API key" | Verify the key at console.anthropic.com; check usage limits |
| No MQTT data arriving | Ensure the MQTT broker is running and topics are publishing |
| Schedule shows all "idle" | Claude returned an empty schedule; check HA logs for Claude errors |
| Battery level stuck at 50% | Configure the optional battery MQTT topic or publish level data |
| UPS not charging/discharging | Verify your device subscribes to the correct MQTT topics and responds to `1`/`0` payloads |

Enable debug logging for detailed diagnostics:

```yaml
# configuration.yaml
logger:
  logs:
    custom_components.pstryk_ups: debug
```

---

## Contributing

Bug reports and pull requests are welcome at [github.com/piotr-siedlak/hacs-pstryk-ups-ai](https://github.com/piotr-siedlak/hacs-pstryk-ups-ai).

---

## License

MIT License — see `LICENSE` for details.
