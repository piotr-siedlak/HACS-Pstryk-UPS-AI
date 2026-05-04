# Pstryk UPS AI Optimizer

A production-ready [Home Assistant](https://www.home-assistant.io/) custom integration installable via [HACS](https://hacs.xyz/) that automatically optimises UPS battery charging and discharging cycles based on real-time electricity prices from the **Pstryk API** and AI-powered scheduling via **Claude (Anthropic)**.

---

## Features

- **Full electricity price** — fetches `full_price` (TGE spot + distribution + service + VAT + excise) from the Pstryk API, so scheduling decisions reflect what you actually pay
- **Cheap/expensive flags** — Pstryk's own `is_cheap` / `is_expensive` signals are passed to Claude as additional hints alongside the raw prices
- **Current-day and next-day prices** — after ~15:00 Warsaw time, next-day TGE prices are automatically included so Claude can optimise across midnight
- **AI schedule planning** — sends prices, household consumption history, and battery constraints to Claude, which returns a 24-hour hourly charge/discharge plan optimised to minimise cost
- **Configurable Claude prompt** — the full prompt sent to Claude is editable from the Configure panel; use `{variable}` placeholders to inject live data
- **Heuristic fallback** — if Claude is unavailable, a deterministic algorithm charges during the cheapest hours and discharges during the most expensive, respecting battery min/max at all times
- **Configurable battery constraints** — set minimum (reserve) and maximum charge % passed directly to Claude for realistic planning
- **MQTT integration (optional)** — subscribes to configurable topics for real-time power draw, historical consumption, and battery state of charge; publishes `1`/`0` commands to separate charge and discharge control topics. All MQTT topics are optional — the integration works for price fetching and scheduling without them
- **Real-time MQTT sensor updates** — sensor values update instantly on every incoming MQTT message, not just on the hourly coordinator cycle
- **API status monitoring** — dedicated sensors show whether the Pstryk and Claude APIs are reachable, with last request URL, last-success timestamp, last error, last prompt sent, and MQTT connection status
- **Dedicated API URL and prompt sensors** — `Last Pstryk API Request URL` and `Last Claude Prompt` are standalone sensors visible directly in the HA dashboard, not buried in attributes
- **Periodic MQTT heartbeat** — charge/discharge state is re-published to MQTT every N seconds (configurable, default 30 s), so the UPS resyncs automatically after a power cycle or missed message
- **13 sensor entities** — electricity price, power draw, schedule status, next charge/discharge windows, battery level, daily savings estimate, Pstryk API status, Claude API status, last Pstryk request URL, last Claude prompt, schedule next 24h timeline, schedule past 3h timeline
- **3 switch entities** — manual charging toggle, manual discharging toggle, auto-schedule enable/disable
- **Configurable MQTT repeat interval** — set how often (in seconds) the charge/discharge commands are re-sent; adjustable from 10 s to 3600 s in the Configure panel
- **1 button entity** — manual price refresh that immediately fetches fresh Pstryk prices and regenerates the schedule, without affecting the automatic hourly cron
- **Single-page Configure panel** — update all UPS parameters, MQTT topics, and the Claude prompt together on one screen; changes take effect immediately after saving
- **Reconfigure support** — update API keys independently without touching UPS or MQTT settings
- **English and Polish translations**

---

## Requirements

| Requirement | Details |
|---|---|
| Home Assistant | 2024.1.0 or newer |
| HACS | 1.31.0 or newer |
| Python package | `anthropic>=0.40.0` (installed automatically) |
| HA integration | MQTT (optional — configure in HA if UPS control via MQTT is needed) |
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
- **MQTT broker** (optional) — configure in Home Assistant under Settings → Devices & Services → MQTT if you want UPS charge/discharge control. The integration loads and fetches prices without MQTT.

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

All MQTT topic fields are **optional**. Leave them empty to skip and configure later from the Configure panel.

| Field | Description |
|---|---|
| Real-time Power Topic | MQTT topic publishing household power draw in kW |
| Historical Consumption Topic | MQTT topic publishing JSON consumption history |
| UPS Charge Control Topic | MQTT topic that receives `1`/`0` charge commands |
| UPS Discharge Control Topic | MQTT topic that receives `1`/`0` discharge commands |
| Battery Level Topic | MQTT topic publishing battery state of charge in % |
| Price Refresh Interval | How often (in hours) to fetch new prices from Pstryk (default: 6) |
| MQTT Repeat Interval | How often (in seconds) to re-publish the current charge/discharge state to MQTT (default: 30) |

### Changing settings after setup

Go to **Settings → Devices & Services → Pstryk UPS AI Optimizer → Configure** to update all UPS parameters, MQTT topics, and the Claude prompt on a single page. Changes take effect immediately after saving.

To update API keys, use the **Reconfigure** option from the integration's three-dot (⋮) menu.

### MQTT broker connection

MQTT broker credentials (host, port, username, password) are configured **once** in Home Assistant's built-in MQTT integration — not in this integration. This integration only needs the topic names.

To set up the MQTT broker: **Settings → Devices & Services → Add Integration → MQTT**.

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
{"battery_level": 75.5}
```

### Charge / Discharge control topics (publish)

The integration publishes `1` (enable) or `0` (disable) — retained, QoS 1 — whenever:
- The auto-schedule activates or deactivates charging/discharging for the current hour
- The user toggles the **UPS Charging** or **UPS Discharging** switch manually
- The MQTT repeat interval elapses (default: every 30 seconds — heartbeat to keep the UPS in sync)

---

## Entities

### Sensors

| Entity ID | Description | Unit | Key Attributes |
|---|---|---|---|
| `sensor.pstryk_ups_electricity_price` | Current total electricity price (incl. all fees and taxes) | PLN/kWh | `upcoming_prices`, `last_refresh`, `price_count` |
| `sensor.pstryk_ups_household_power_draw` | Live household power draw from MQTT | kW | `history_daily_entries`, `history_hourly_entries` |
| `sensor.pstryk_ups_schedule_status` | Current scheduled action | charge / discharge / idle | `schedule` (full 24-h list), `schedule_hours`, `auto_schedule_enabled` |
| `sensor.pstryk_ups_next_charge_window` | Start of the next planned charging window | timestamp | `charge_windows` |
| `sensor.pstryk_ups_next_discharge_window` | Start of the next planned discharge window | timestamp | `discharge_windows` |
| `sensor.pstryk_ups_battery_level` | Battery state of charge from MQTT | % | `projected_end_level_pct` |
| `sensor.pstryk_ups_estimated_daily_savings` | Estimated PLN saved today vs always-idle | PLN | `scheduled_charge_hours`, `scheduled_discharge_hours` |
| `sensor.pstryk_ups_pstryk_api_status` | Pstryk API reachability | ok / error / unknown | `last_request`, `last_success`, `last_error`, `last_checked`, `next_day_prices_available`, `mqtt_status`, `mqtt_power_topic`, `mqtt_last_power_update`, `mqtt_history_topic`, `mqtt_last_history_update`, `mqtt_charge_topic`, `mqtt_discharge_topic`, `mqtt_battery_topic`, `mqtt_last_battery_update` |
| `sensor.pstryk_ups_claude_api_status` | Claude AI API status and schedule source | ok / error / unknown | `last_request`, `last_success`, `last_error`, `schedule_source` (claude / heuristic), `last_prompt` |
| `sensor.pstryk_ups_last_pstryk_api_request_url` | Last Pstryk API request URL (max 255 chars) | — | `full_url` (complete URL) |
| `sensor.pstryk_ups_last_claude_prompt` | Summary of the last Claude prompt (char count / line count) | — | `full_prompt` (complete prompt text), `last_request_info` |
| `sensor.pstryk_ups_schedule_next_24h` | Summary of the next 24 h schedule (e.g. `5× charge  3× discharge  16× idle`) | — | `slots` — list of `{label, hour, action, price, power_kw, battery_pct, reason}` for Now through Now +24 |
| `sensor.pstryk_ups_schedule_past_3h` | Summary of the past 3 h from the schedule (e.g. `3h: 2× charge  1× idle`) | — | `slots` — list of `{label, hour, action, price, power_kw, battery_pct, reason}` for Now -3 through Now -1 |

### Switches

| Entity ID | Description |
|---|---|
| `switch.pstryk_ups_ups_charging` | Enable/disable UPS charging — publishes `1`/`0` to the charge control topic |
| `switch.pstryk_ups_ups_discharging` | Enable/disable UPS discharging — publishes `1`/`0` to the discharge control topic |
| `switch.pstryk_ups_auto_schedule` | Enable/disable AI-driven automatic scheduling |

### Buttons

| Entity ID | Description |
|---|---|
| `button.pstryk_ups_refresh_prices` | Immediately fetches fresh prices from the Pstryk API and regenerates the charge/discharge schedule. Bypasses the configured refresh interval TTL. The automatic hourly schedule is unaffected. |

---

## How the AI Scheduling Works

1. Every hour the coordinator checks whether prices need refreshing based on the configured interval.
2. Prices fetched from Pstryk use the `full_price` field — the true all-inclusive price: TGE spot + distribution + service + VAT + excise. Each hourly record also carries `is_cheap` and `is_expensive` flags set by Pstryk.
3. Current-day prices are always available. After ~15:00 Warsaw time the window is automatically extended to include next-day TGE prices, so Claude can optimise overnight cycles.
4. When fresh prices arrive, they are sent to Claude along with:
   - Your UPS configuration (capacity, charge/discharge rates, min/max battery %)
   - Current household power draw (from MQTT)
   - Historical consumption data from MQTT (past 7 days)
   - Current battery state of charge
   - `is_cheap` / `is_expensive` flags per hour as additional hints
5. Claude returns a 24-hour schedule with hourly actions (`charge`, `discharge`, `idle`), planned power (kW), price context, reason, and projected battery level.
6. If Claude fails (API error, network issue, unparseable response), the integration automatically falls back to a heuristic:
   - Charge during the cheapest upcoming hours
   - Discharge during the most expensive upcoming hours
   - Battery min/max % constraints always respected
7. The `sensor.pstryk_ups_claude_api_status` sensor shows whether Claude or the heuristic generated the current schedule, exposes any error message, and stores the full last prompt sent to Claude in its `last_prompt` attribute.
8. When **Auto Schedule** is ON, both charging and discharging switches update automatically each hour to follow the plan.
9. You can override at any time by toggling the switches manually — overrides last until the next hourly update when auto-schedule re-applies.

---

## Customising the Claude Prompt

The full prompt sent to Claude is stored in the Configure panel and can be edited freely. Open **Settings → Devices & Services → Pstryk UPS AI Optimizer → Configure** and scroll to the **Claude AI Prompt** field.

The prompt uses Python `str.format()` placeholders filled at runtime:

| Placeholder | Content |
|---|---|
| `{ups_model}` | UPS model name |
| `{capacity_kwh}` | Battery capacity in kWh |
| `{num_strings}` | Number of battery strings |
| `{max_charge}` | Max charge rate in kW |
| `{max_discharge}` | Max discharge rate in kW |
| `{current_battery_pct}` | Current battery level % |
| `{battery_min_pct}` | Configured minimum battery % |
| `{battery_max_pct}` | Configured maximum battery % |
| `{price_table}` | Hourly price table with `full_price`, `is_cheap`, `is_expensive` |
| `{current_power_kw}` | Current household power draw in kW |
| `{history_summary}` | JSON consumption history (last 7 days) |

Use `{{` and `}}` for literal braces in JSON examples within your prompt. If the custom prompt contains an invalid placeholder, the integration automatically falls back to the built-in default.

The last prompt actually sent to Claude is visible in two ways:
- As the state of `sensor.pstryk_ups_last_claude_prompt` (shows character and line count)
- As the `full_prompt` attribute of the same sensor (complete prompt text)
- Also in `sensor.pstryk_ups_claude_api_status` → `last_prompt` attribute

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
  - entity: sensor.pstryk_ups_last_pstryk_api_request_url
  - entity: sensor.pstryk_ups_last_claude_prompt
  - entity: sensor.pstryk_ups_schedule_next_24h
  - entity: sensor.pstryk_ups_schedule_past_3h
  - entity: button.pstryk_ups_refresh_prices
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
| Electricity price shows 0 or wrong value | Check `sensor.pstryk_ups_pstryk_api_status` → `last_error`; the `last_request` attribute shows the exact URL that was called |
| Claude status shows "error" | Check `sensor.pstryk_ups_claude_api_status` → `last_error`; the heuristic fallback is active |
| Schedule source shows "heuristic" | Claude API returned an error — check your Anthropic API key and credit balance |
| Sensors not updating from MQTT | Check `sensor.pstryk_ups_pstryk_api_status` → `mqtt_status` and `mqtt_last_power_update` / `mqtt_last_battery_update` to confirm messages are arriving |
| MQTT status shows "unavailable" | The HA MQTT integration is not set up — go to Settings → Devices & Services → Add Integration → MQTT and configure your broker |
| MQTT status shows "no_topics" | MQTT is connected but no topics are configured — go to Configure and fill in the topic fields |
| No MQTT data arriving | Verify your device is publishing to the topics shown in `sensor.pstryk_ups_pstryk_api_status` attributes |
| Schedule shows all "idle" | Claude returned an empty or unparseable schedule; check `last_prompt` attribute for what was sent, and HA logs for details |
| Battery level stuck at 50% | Verify your device is publishing to the configured battery MQTT topic; check `mqtt_last_battery_update` |
| UPS not charging/discharging | Verify your device subscribes to the correct MQTT topics and responds to `1`/`0` payloads |
| Custom prompt not working | Check `last_prompt` attribute on the Claude sensor to see what was actually rendered; ensure all `{placeholder}` names are correct and literal braces use `{{` / `}}` |
| Where to set MQTT broker IP/port/password | These go in the HA built-in MQTT integration, not here — Settings → Devices & Services → MQTT |

Enable debug logging for detailed diagnostics:

```yaml
# configuration.yaml
logger:
  logs:
    custom_components.pstryk_ups: debug
```

---

## Changelog

### v1.10.14
- **Next-day price publish hour updated**: TGE now publishes next-day spot prices at **12:00 Warsaw** (previously assumed 15:00). The `NEXT_DAY_PRICES_HOUR` constant is updated accordingly, so the integration now extends the fetch window to cover the full next day from midday onwards, giving Claude an extra 3 hours of forward-looking data for better overnight schedule optimisation.

### v1.10.13
- **Stale-price watchdog**: Added a dedicated 5-minute background task that runs independently of the hourly coordinator cycle.  Whenever it detects that the cached price window does not cover the current UTC hour, it forces an immediate refresh by mirroring the manual Refresh Prices button (resets `last_price_refresh = None` then requests an update).  This is the **definitive** fix for the midnight / day-change "no data" symptom — the integration now self-heals within at most 5 minutes regardless of when HA was started, the configured refresh interval, or whether the previous hourly cycle landed on the rollover boundary.  When the watchdog triggers, full diagnostic context (cache size, first/last cached timestamps, current UTC hour) is logged at WARNING level so the underlying cause is visible.

### v1.10.12
- **Midnight "no data" definitive fix**: Added a 6th refresh trigger — if the cached price window does not contain an entry for the **current UTC hour**, a re-fetch is forced immediately regardless of TTL or any other state. This directly mirrors the mechanism used by the manual "Refresh Prices" button and is the most reliable fix for the midnight rollover gap. Additionally, when the schedule has no future entries, the price TTL is now reset (`last_price_refresh = None`) so the **next** hourly cycle performs a full re-fetch instead of regenerating from potentially stale cached prices.

### v1.10.11
- **Midnight "no data" fix**: Root cause identified — the schedule is only regenerated when prices are re-fetched, so when the 24-hour Claude schedule window expired at midnight the sensor showed "no data" until the next TTL-based price fetch. Two fixes: (1) if all cached prices are now in the past, force an immediate re-fetch regardless of TTL; (2) if prices exist but the schedule has no future entries, regenerate the schedule from cached prices on the next hourly coordinator cycle — no manual "Refresh Prices" needed

### v1.10.10
- **Blocking SSL call fix**: `anthropic.AsyncAnthropic()` was calling `ssl.load_verify_locations()` during `__init__` — a blocking I/O operation forbidden inside the HA event loop. The client is now created lazily on first use via `run_in_executor`, eliminating the `Detected blocking call` warning in HA logs
- **Extended midnight retry**: Price retry now runs in two phases — 5 fast retries every 60 s (5 min), then slow retries every 5 min for up to 3 h total. This covers the full TGE midnight transition window instead of giving up after 5 minutes and waiting for the next hourly cycle

### v1.10.9
- **Full-battery charging fix**: When the battery is already at or above `battery_max_pct`, Claude no longer schedules charge actions. Two-layer enforcement: (1) explicit `⚠️ Current Battery State` warning in the prompt so Claude understands the constraint upfront; (2) hard post-processing pass in `_parse_schedule` that overrides any `charge` → `idle` when simulated battery level is at max (and vice-versa for discharge at min). Overrides are logged at INFO level and visible in the slot `reason` field prefixed with `[overridden: ...]`

### v1.10.8
- **Midnight price retry**: When the Pstryk API returns 0 price records (common during the TGE midnight transition), the integration now schedules up to 5 automatic retries, 60 seconds apart, without waiting for the next hourly cycle
- **Empty-price bug fix**: Previously, a successful HTTP 200 response with 0 frames still updated `last_price_refresh`, preventing any retry for up to 6 hours. Now `last_price_refresh` is only updated when actual prices are received
- **4th refresh trigger**: The coordinator now always attempts a fresh fetch when the current price list is empty, regardless of TTL state

### v1.10.6
- **Schedule timeline sensors**: Added `sensor.pstryk_ups_schedule_next_24h` (slots labelled `Now`, `Now +1` … `Now +24`) and `sensor.pstryk_ups_schedule_past_3h` (slots labelled `Now -3`, `Now -2`, `Now -1`). State is a human-readable action summary; `slots` attribute contains the full structured list for use in Lovelace Markdown cards

### v1.10.5
- **Dedicated API URL and prompt sensors**: Added `sensor.pstryk_ups_last_pstryk_api_request_url` (state = last URL called, attribute `full_url`) and `sensor.pstryk_ups_last_claude_prompt` (state = char/line count, attribute `full_prompt` = complete prompt text). These are now visible directly in the HA dashboard without digging into attributes
- **Periodic MQTT heartbeat**: Charge/discharge state is now re-published to MQTT every N seconds (default 30 s, configurable 10–3600 s from Configure panel). Ensures UPS stays in sync after power cycles or missed messages without waiting for the next schedule change

### v1.10.4
- **Last API request visibility**: `sensor.pstryk_ups_pstryk_api_status` now shows the exact URL sent to the Pstryk API in `last_request`; `sensor.pstryk_ups_claude_api_status` shows the Anthropic API call summary in `last_request` and the full rendered prompt in `last_prompt`
- **Real-time MQTT sensor updates**: Fixed sensors updating only on the hourly cycle — values now update instantly on every incoming MQTT message
- **MQTT last-update timestamps**: Each MQTT data topic has a `mqtt_last_power_update`, `mqtt_last_history_update`, `mqtt_last_battery_update` timestamp visible in sensor attributes

### v1.9.0
- **MQTT now optional**: Integration loads and fetches prices even when the HA MQTT integration is not set up. All MQTT topic fields are optional in the setup wizard and Configure panel. `mqtt_status` (`connected` / `no_topics` / `unavailable`) and configured topic names visible in `sensor.pstryk_ups_pstryk_api_status` attributes

### v1.8.0
- **Cheap/expensive price flags**: Pstryk's `is_cheap` and `is_expensive` booleans are now fetched per hour and included in the price table sent to Claude
- **Configurable Claude prompt**: The full prompt template is editable from the Configure panel. Supports `{variable}` placeholders for live data injection. Custom prompt visible and auditable via `last_prompt` attribute on the Claude sensor

### v1.7.0
- **Price field corrected**: Now uses `full_price` from the Pstryk API — the true all-inclusive price (TGE spot + distribution + service + VAT + excise). Previous versions were falling back to `tge_price` (raw TGE spot only, can be near-zero or negative), causing wildly wrong scheduling decisions

### v1.6.0
- **Manual refresh button**: Added `button.pstryk_ups_refresh_prices` — press to immediately fetch fresh Pstryk prices and regenerate the schedule without waiting for the next hourly cycle

### v1.4.0
- **API status sensors**: Added `sensor.pstryk_ups_pstryk_api_status` and `sensor.pstryk_ups_claude_api_status` with last-success timestamp, last error message, and schedule source (claude/heuristic) in attributes
- **Single-page Configure panel**: Merged UPS parameters and MQTT topics into one page
- **Discharging switch**: Added `switch.pstryk_ups_ups_discharging` for manual and auto-schedule controlled discharge

### v1.3.0
- **Auth header fix**: Removed erroneous `Token` prefix from the Pstryk API `Authorization` header — raw key is correct per the Pstryk API spec
- **API parameter fix**: Removed `for_tz` parameter which is not allowed with `resolution=hour` per the Pstryk API documentation

---

## Contributing

Bug reports and pull requests are welcome at [github.com/piotr-siedlak/hacs-pstryk-ups-ai](https://github.com/piotr-siedlak/hacs-pstryk-ups-ai).

---

## License

MIT License — see `LICENSE` for details.
