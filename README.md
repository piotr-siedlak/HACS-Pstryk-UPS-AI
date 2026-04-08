# Pstryk UPS AI Optimizer

A production-ready [Home Assistant](https://www.home-assistant.io/) custom integration installable via [HACS](https://hacs.xyz/) that automatically optimises UPS battery charging and discharging cycles based on real-time electricity prices from the **Pstryk API** and AI-powered scheduling via **Claude (Anthropic)**.

---

## Features

- **Live electricity prices** — fetches current and 48-hour-ahead spot prices from the Pstryk API at a configurable interval
- **AI schedule planning** — sends prices + household consumption history to Claude, which returns an hourly charge/discharge plan optimised to minimise energy costs
- **Heuristic fallback** — if Claude is unavailable the integration falls back to a deterministic algorithm (charge in cheapest N hours, discharge in most expensive N hours)
- **MQTT integration** — subscribes to configurable topics for:
  - Real-time household power draw (kW)
  - Historical consumption data (kWh/day, kWh/hour)
  - Optional UPS battery state of charge (%)
  - Publishes ON/OFF commands to a UPS charge control topic
- **7 sensor entities** — electricity price, power draw, schedule status, next charge/discharge windows, battery level, daily savings estimate
- **2 switch entities** — manual charging toggle and auto-schedule enable/disable
- **Full config flow** — all settings configurable via the Home Assistant UI (no YAML required)
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

#### Step 3 — MQTT Topics & Scheduling

| Field | Required | Description |
|---|---|---|
| Real-time Power Topic | Yes | MQTT topic publishing household power draw in kW |
| Historical Consumption Topic | Yes | MQTT topic publishing JSON consumption history |
| UPS Charge Control Topic | Yes | MQTT topic to receive ON/OFF charge commands |
| Battery Level Topic | No | MQTT topic publishing battery % (improves estimates) |
| Price Refresh Interval | Yes (default 6) | How often (hours) to call the Pstryk API |

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

The integration publishes `ON` or `OFF` (retained, QoS 1) to the configured control topic whenever:
- The auto-schedule activates or deactivates charging
- The user toggles the **UPS Charging** switch in HA

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
| `switch.pstryk_ups_ups_charging` | Enable/disable UPS charging (publishes MQTT) |
| `switch.pstryk_ups_auto_schedule` | Enable/disable AI automatic scheduling |

---

## How the AI Scheduling Works

1. Every hour the coordinator checks whether prices need refreshing (based on your configured interval).
2. When fresh prices are available, they are sent to Claude along with:
   - Your UPS configuration (capacity, charge/discharge rates)
   - Current household power draw
   - Historical consumption data (past 7 days)
   - Current battery level
3. Claude returns a 24-hour schedule with hourly actions (`charge`, `discharge`, `idle`), planned power, price context, and projected battery level.
4. If Claude fails (API error, network issue, invalid response), the integration automatically falls back to a heuristic:
   - Charge during the 8 cheapest upcoming hours
   - Discharge during the 4 most expensive upcoming hours
   - Maintain at least 10% battery reserve at all times
5. When **Auto Schedule** is ON, the charging switch state is automatically updated each hour to follow the plan.
6. You can override at any time by toggling the **UPS Charging** switch — the override lasts until the next hourly update.

---

## Dashboard Example

Add a Lovelace **Entities** card:

```yaml
type: entities
title: UPS AI Optimizer
entities:
  - entity: switch.pstryk_ups_auto_schedule
  - entity: switch.pstryk_ups_ups_charging
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

Enable debug logging for detailed diagnostics:

```yaml
# configuration.yaml
logger:
  logs:
    custom_components.pstryk_ups: debug
```

---

## Reconfiguring API Keys

Go to **Settings → Devices & Services → Pstryk UPS AI Optimizer → Configure** and enter updated keys. The integration reloads automatically.

To change UPS parameters or MQTT topics, remove and re-add the integration.

---

## Contributing

Bug reports and pull requests are welcome at [github.com/piotr-siedlak/hacs-pstryk-ups-ai](https://github.com/piotr-siedlak/hacs-pstryk-ups-ai).

---

## License

MIT License — see `LICENSE` for details.
