"""Async client for the Pstryk electricity pricing API."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import aiohttp

from .const import (
    PSTRYK_API_BASE_URL,
    PSTRYK_API_TIMEOUT,
    PSTRYK_PRICING_ENDPOINT,
)

_LOGGER = logging.getLogger(__name__)


class PstrykAPIError(Exception):
    """Raised when the Pstryk API returns an unexpected response."""


class PstrykAuthError(PstrykAPIError):
    """Raised when the API key is invalid or unauthorised."""


class PstrykAPIClient:
    """Thin async wrapper around the Pstryk REST pricing endpoint.

    The client fetches hourly electricity prices for a configurable window
    (default: now → now + 48 h).  It normalises the response regardless of
    whether the API returns a flat list or a paginated ``results`` envelope,
    and regardless of which exact field names are used for timestamp and price.
    """

    # Field aliases tried in order when parsing each price record
    _TS_FIELDS = ("datetime_from", "datetime", "timestamp", "date_from", "date")
    _PRICE_NET_FIELDS = ("price_net", "price", "net_price", "value", "energy_price")
    _PRICE_GROSS_FIELDS = ("price_gross", "gross_price", "price_with_vat")

    def __init__(self, api_key: str, session: aiohttp.ClientSession) -> None:
        self._api_key = api_key
        self._session = session
        self._base_url = PSTRYK_API_BASE_URL.rstrip("/")

    # ── Public methods ──────────────────────────────────────────────────────

    async def async_get_prices(
        self,
        hours_ahead: int = 48,
    ) -> list[dict[str, Any]]:
        """Return a list of hourly price records for the next *hours_ahead* hours.

        Each record contains:
        - ``timestamp``   – ISO-8601 string (start of the hour, UTC)
        - ``price``       – net price in PLN/kWh (float)
        - ``price_gross`` – gross price in PLN/kWh (float); equals ``price``
                            when the API does not expose a gross field
        """
        now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        date_from = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        date_to = (now + timedelta(hours=hours_ahead)).strftime("%Y-%m-%dT%H:%M:%SZ")

        url = f"{self._base_url}{PSTRYK_PRICING_ENDPOINT}"
        headers = {
            "Authorization": f"Token {self._api_key}",
            "Accept": "application/json",
        }
        params = {"date_from": date_from, "date_to": date_to}

        _LOGGER.debug("Fetching Pstryk prices: %s params=%s", url, params)

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
            raise PstrykAPIError(f"Network error contacting Pstryk API: {exc}") from exc

        records = self._extract_records(payload)
        parsed = [self._parse_record(r) for r in records]
        prices = [p for p in parsed if p is not None]

        _LOGGER.debug("Parsed %d price records from Pstryk API", len(prices))
        return prices

    async def async_validate_key(self) -> bool:
        """Return True when the API key is accepted (HTTP 200 or empty result)."""
        try:
            await self.async_get_prices(hours_ahead=2)
            return True
        except PstrykAuthError:
            return False
        except PstrykAPIError as exc:
            _LOGGER.warning("Pstryk API validation error: %s", exc)
            # A non-auth error (e.g. 500) is treated as an ambiguous result;
            # we allow the user to save the key and retry at runtime.
            return True

    # ── Private helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _extract_records(payload: Any) -> list[Any]:
        """Normalise the API envelope into a flat list of price items."""
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            for key in ("results", "prices", "data", "items"):
                if key in payload and isinstance(payload[key], list):
                    return payload[key]
            # Last resort: treat the dict itself as a single record
            return [payload]
        return []

    def _parse_record(self, record: dict[str, Any]) -> dict[str, Any] | None:
        """Parse a single price record into a normalised dict, or None on error."""
        if not isinstance(record, dict):
            return None

        # Timestamp
        ts_raw: str | None = None
        for field in self._TS_FIELDS:
            if field in record and record[field]:
                ts_raw = str(record[field])
                break
        if ts_raw is None:
            _LOGGER.debug("Skipping price record with no timestamp: %s", record)
            return None

        # Normalise timestamp to UTC ISO-8601
        try:
            ts_raw = ts_raw.replace(" ", "T")
            if not ts_raw.endswith("Z") and "+" not in ts_raw and ts_raw[-3] != ":":
                ts_raw += "Z"
            # Validate by parsing (raises ValueError on bad format)
            datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
        except ValueError:
            _LOGGER.debug("Unparseable timestamp %r, skipping record", ts_raw)
            return None

        # Net price
        price_net: float = 0.0
        for field in self._PRICE_NET_FIELDS:
            if field in record and record[field] is not None:
                try:
                    price_net = float(record[field])
                    break
                except (TypeError, ValueError):
                    pass

        # Gross price (falls back to net when absent)
        price_gross: float = price_net
        for field in self._PRICE_GROSS_FIELDS:
            if field in record and record[field] is not None:
                try:
                    price_gross = float(record[field])
                    break
                except (TypeError, ValueError):
                    pass

        return {
            "timestamp": ts_raw,
            "price": price_net,
            "price_gross": price_gross,
        }
