"""Async client for the Pstryk electricity pricing API.

Prices come from the TGE (Polish Power Exchange) spot market:
  - Current-day prices: always available.
  - Next-day prices:    published each afternoon, typically around 14:00–15:00
                        Warsaw/CET time.  Before that hour only today's prices
                        exist; after it we extend the fetch window to cover the
                        full next day.

Endpoint used:
    GET /integrations/meter-data/unified-metrics/
        ?metrics=pricing
        &resolution=hour
        &window_start=<ISO8601 UTC>
        &window_end=<ISO8601 UTC>
        &for_tz=Europe/Warsaw
    Authorization: Token <api_key>

Response shape:
    {
      "frames": [
        {
          "start": "2026-04-09T11:00:00Z",
          "end":   "2026-04-09T12:00:00Z",
          "metrics": {
            "pricing": {
              "tge_price":        -0.002,    ← raw TGE spot price (can be negative)
              "dist_price":        0.4711,   ← distribution tariff
              "service_price":     0.08,     ← service fee
              "base_price":        0.5491,   ← tge + dist + service (no VAT)
              "vat_component":     0.1263,   ← VAT
              "excise_component":  0.005,    ← excise duty
              "full_price":        0.6804,   ← THE CORRECT FIELD: total all-in price
              "price_net":        -0.002,    ← alias for tge_price (NOT the full price)
              "price_gross":       0.6804,   ← alias for full_price (identical)
              "is_cheap":          true,
              "is_expensive":      false
            }
          }
        },
        ...
      ],
      "summary": { "pricing": { "full_price_avg": 0.96, ... } }
    }
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import aiohttp

from .const import (
    NEXT_DAY_PRICES_HOUR,
    PSTRYK_API_BASE_URL,
    PSTRYK_API_TIMEOUT,
    PSTRYK_UNIFIED_ENDPOINT,
    WARSAW_TZ_NAME,
)

_LOGGER = logging.getLogger(__name__)
_WARSAW = ZoneInfo(WARSAW_TZ_NAME)


class PstrykAPIError(Exception):
    """Raised when the Pstryk API returns an unexpected response."""


class PstrykAuthError(PstrykAPIError):
    """Raised when the API key is invalid or unauthorised."""


class PstrykAPIClient:
    """Thin async wrapper around the Pstryk unified-metrics pricing endpoint."""

    # Field aliases tried in order when extracting the full customer price from a frame.
    # full_price = tge_price + dist_price + service_price + vat_component + excise_component
    # price_gross is identical to full_price in the Pstryk API response.
    # price_net / tge_price is the raw TGE spot price only (no distribution, no taxes) — NOT suitable.
    _PRICE_NET_FIELDS = (
        "full_price", "total_cost", "fix_price", "net_price", "price", "tge_price", "energy_price", "value"
    )
    _PRICE_GROSS_FIELDS = (
        "price_gross", "gross_price", "price_with_vat", "gross"
    )

    def __init__(self, api_key: str, session: aiohttp.ClientSession) -> None:
        self._api_key = api_key
        self._session = session
        self._base_url = PSTRYK_API_BASE_URL.rstrip("/")

    # ── Window helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def get_fetch_window() -> tuple[datetime, datetime, bool]:
        """Return ``(window_start, window_end, includes_next_day)``.

        Pstryk API parameter semantics (from the official documentation):
          ``window_start=T`` → the **first** returned period starts at T
                               (e.g. T=11:00Z → period 11:00–12:00Z is first)
          ``window_end=T``   → the **last** returned period *ends* at T
                               (e.g. T=11:00Z → period 10:00–11:00Z is last)

        Therefore:
          * ``window_start`` = floor of the current UTC hour  (inclusive start)
          * ``window_end``   = Warsaw midnight (00:00) of tomorrow, expressed in
                               UTC.  This is the end-of-period wall-clock for the
                               final Warsaw hour of the day (23:00–00:00 Warsaw).

        After ``NEXT_DAY_PRICES_HOUR`` in Warsaw (TGE publishes next-day prices
        ~14:00–15:00 CET), we extend ``window_end`` by one more day so that the
        full next-day price table is included in one API call.
        """
        now_utc = datetime.now(timezone.utc)
        now_warsaw = now_utc.astimezone(_WARSAW)

        # window_start: start of the current Warsaw hour expressed in UTC.
        # API will return the period [window_start, window_start+1h) as the first frame.
        window_start = now_utc.replace(minute=0, second=0, microsecond=0)

        # Tomorrow midnight Warsaw = "end" of the last hour of today (23:00–00:00 Warsaw).
        # Expressed as UTC this is tomorrow's 22:00 UTC (CET) or 21:00 UTC (CEST).
        today_midnight_warsaw = (
            now_warsaw.replace(hour=0, minute=0, second=0, microsecond=0)
            + timedelta(days=1)
        )

        includes_next_day = now_warsaw.hour >= NEXT_DAY_PRICES_HOUR
        if includes_next_day:
            # Extend to end of tomorrow: day-after-tomorrow 00:00 Warsaw → UTC
            window_end = (today_midnight_warsaw + timedelta(days=1)).astimezone(timezone.utc)
        else:
            window_end = today_midnight_warsaw.astimezone(timezone.utc)

        return window_start, window_end, includes_next_day

    # ── Public API ───────────────────────────────────────────────────────────────

    async def async_get_prices(self) -> tuple[list[dict[str, Any]], bool]:
        """Fetch hourly TGE spot prices for the available window.

        Returns ``(prices, includes_next_day)`` where:
        - ``prices`` is a list of ``{"timestamp", "price", "price_gross"}`` dicts.
        - ``includes_next_day`` is True when the response covers tomorrow's prices.

        Before 15:00 Warsaw only current-day remaining hours are returned.
        After 15:00 Warsaw the full next day is included as well.
        """
        window_start, window_end, includes_next_day = self.get_fetch_window()

        url = f"{self._base_url}{PSTRYK_UNIFIED_ENDPOINT}"
        headers = {
            "Authorization": self._api_key,
            "Accept": "application/json",
        }
        params = {
            "metrics": "pricing",
            "resolution": "hour",
            "window_start": window_start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "window_end": window_end.strftime("%Y-%m-%dT%H:%M:%SZ"),
            # for_tz is NOT allowed with resolution=hour per the Pstryk API spec
        }

        _LOGGER.debug(
            "Fetching Pstryk prices  %s → %s  includes_next_day=%s",
            params["window_start"], params["window_end"], includes_next_day,
        )

        try:
            async with self._session.get(
                url,
                headers=headers,
                params=params,
                timeout=aiohttp.ClientTimeout(total=PSTRYK_API_TIMEOUT),
            ) as resp:
                if resp.status == 401:
                    raise PstrykAuthError("Invalid Pstryk API key (HTTP 401)")
                if resp.status == 403:
                    raise PstrykAuthError("Pstryk API key lacks permission (HTTP 403)")
                if resp.status != 200:
                    body = await resp.text()
                    raise PstrykAPIError(
                        f"Pstryk API returned HTTP {resp.status}: {body[:200]}"
                    )
                payload = await resp.json(content_type=None)
        except aiohttp.ClientError as exc:
            raise PstrykAPIError(
                f"Network error contacting Pstryk API: {exc}"
            ) from exc

        prices = self._parse_unified_response(payload)
        _LOGGER.info(
            "Fetched %d price records from Pstryk (includes_next_day=%s)",
            len(prices), includes_next_day,
        )
        return prices, includes_next_day

    async def async_validate_key(self) -> bool:
        """Return True when the API key is accepted by the server.

        Makes a lightweight GET to the unified-metrics endpoint with no data
        parameters — sufficient to trigger an auth check without needing a
        valid query window.  Only HTTP 401 is treated as a definitive "wrong
        key" signal.  HTTP 403 means the key reached the server but may lack a
        specific plan permission — still a valid credential.  Any other
        response (200, 400, 404 …) also means the key was accepted.
        """
        url = f"{self._base_url}{PSTRYK_UNIFIED_ENDPOINT}"
        headers = {
            "Authorization": self._api_key,
            "Accept": "application/json",
        }
        try:
            async with self._session.get(
                url,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=PSTRYK_API_TIMEOUT),
            ) as resp:
                _LOGGER.debug(
                    "Pstryk key validation: HTTP %s from %s", resp.status, url
                )
                return resp.status != 401
        except aiohttp.ClientError as exc:
            # Network unreachable — cannot validate; let the user proceed and
            # discover connectivity issues at runtime.
            _LOGGER.warning("Pstryk key validation: network error — %s", exc)
            raise

    # ── Response parsing ──────────────────────────────────────────────────────────

    def _parse_unified_response(self, payload: Any) -> list[dict[str, Any]]:
        """Parse the unified-metrics API response into a flat price list."""
        if not isinstance(payload, dict):
            _LOGGER.warning(
                "Unexpected Pstryk response type %s; expected dict", type(payload).__name__
            )
            return []

        frames = payload.get("frames", [])
        if not isinstance(frames, list):
            _LOGGER.warning("'frames' field missing or not a list in Pstryk response")
            return []

        # Log the first raw frame at DEBUG so users can see the actual field names
        if frames:
            _LOGGER.debug("Pstryk raw first frame: %s", frames[0])

        prices: list[dict[str, Any]] = []
        for frame in frames:
            record = self._parse_frame(frame)
            if record is not None:
                prices.append(record)

        return prices

    def _parse_frame(self, frame: Any) -> dict[str, Any] | None:
        """Extract one price record from a single frame dict."""
        if not isinstance(frame, dict):
            return None

        # ── Timestamp ──────────────────────────────────────────────────────────────
        # Primary field is "start" per the documented example; fall back to
        # other plausible names the API might use.
        ts_raw: str | None = (
            frame.get("start")
            or frame.get("window_start")
            or frame.get("datetime_from")
            or frame.get("datetime")
            or frame.get("timestamp")
        )
        if not ts_raw:
            _LOGGER.debug("Skipping frame with no timestamp: %s", frame)
            return None

        try:
            ts_raw = str(ts_raw).strip().replace(" ", "T")
            # Ensure the string is timezone-aware before parsing
            if ts_raw.endswith("Z"):
                pass  # already UTC
            elif "+" not in ts_raw[-6:] and ts_raw[-3] != ":":
                ts_raw += "Z"
            datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))  # validate
        except ValueError:
            _LOGGER.debug("Unparseable frame timestamp %r — skipping", ts_raw)
            return None

        # ── Pricing data ───────────────────────────────────────────────────────────
        # Look first inside metrics.pricing (documented shape), then fall back
        # to a flat layout where fields live directly on the frame.
        pricing_src: dict[str, Any] = {}
        metrics = frame.get("metrics")
        if isinstance(metrics, dict):
            candidate = metrics.get("pricing")
            if isinstance(candidate, dict):
                pricing_src = candidate

        if not pricing_src:
            # Flat layout: the frame itself carries the price fields
            pricing_src = frame

        price_net, net_field = self._extract_price(pricing_src, self._PRICE_NET_FIELDS)
        price_gross, gross_field = self._extract_price(pricing_src, self._PRICE_GROSS_FIELDS)
        if price_gross == 0.0:
            # API may not expose a separate gross field; fall back to net
            price_gross = price_net

        _LOGGER.debug(
            "Frame %s: price=%.4f (field=%r), price_gross=%.4f (field=%r) | available keys: %s",
            ts_raw[:16], price_net, net_field, price_gross, gross_field,
            list(pricing_src.keys()),
        )

        return {
            "timestamp": ts_raw,
            "price": price_net,
            "price_gross": price_gross,
        }

    @staticmethod
    def _extract_price(
        data: dict[str, Any], field_names: tuple[str, ...], label: str = ""
    ) -> tuple[float, str]:
        """Return ``(value, field_name)`` for the first parseable float found."""
        for field in field_names:
            val = data.get(field)
            if val is not None:
                try:
                    return float(val), field
                except (TypeError, ValueError):
                    pass
        return 0.0, ""
