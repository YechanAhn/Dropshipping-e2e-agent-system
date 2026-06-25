"""
Exchange rate API client.

Fetches live exchange rates from an external provider with in-memory caching
(1-hour TTL) and a hardcoded fallback table for resilience when the upstream
API is unavailable.
"""

import time
from decimal import Decimal
from typing import Any

import httpx

from dropagent.config import ExchangeRateSettings, get_settings
from dropagent.utils.exceptions import APIError
from dropagent.utils.logging import get_logger

logger = get_logger(__name__)

# Cache lifetime in seconds (1 hour)
CACHE_TTL = 3600

# Hardcoded fallback rates (approximate). This is the SINGLE last-resort table,
# used ONLY when the live exchange-rate API is unreachable -- never as the primary
# rate. Base currency: USD.
FALLBACK_RATES: dict[str, Decimal] = {
    # Conservative current USD->KRW (~1500). Erring high protects margin when the
    # live rate is unavailable (under-pricing a USD-sourced item loses money).
    "KRW": Decimal("1500.00"),
    "CNY": Decimal("7.25"),
    "JPY": Decimal("155.00"),
    "EUR": Decimal("0.92"),
    "GBP": Decimal("0.79"),
    "USD": Decimal("1.00"),
}


def to_krw(amount: Decimal, currency: str, usd_krw_rate: Decimal) -> Decimal:
    """
    Convert *amount* in *currency* to KRW.

    KRW passes through untouched (e.g. a price AliExpress already returned in
    won via ``target_currency=KRW``). Anything else is treated as USD-equivalent
    and multiplied by the *live* ``usd_krw_rate`` supplied by the caller. This is
    the single place currency normalisation happens -- callers must never embed
    a literal FX rate.
    """
    cur = (currency or "USD").upper()
    if cur == "KRW":
        return amount
    return amount * usd_krw_rate


class _CacheEntry:
    """Simple timestamped cache entry."""

    __slots__ = ("rates", "timestamp")

    def __init__(self, rates: dict[str, Decimal]) -> None:
        self.rates = rates
        self.timestamp = time.monotonic()

    def is_expired(self) -> bool:
        return (time.monotonic() - self.timestamp) >= CACHE_TTL


class ExchangeRateClient:
    """
    Async exchange rate client with in-memory caching and hardcoded fallback.

    Rates are cached per base currency for up to 1 hour.  If the upstream
    API request fails, the client falls back to a built-in rate table so
    that downstream pricing calculations are never completely blocked.
    """

    def __init__(
        self,
        settings: ExchangeRateSettings | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        """
        Args:
            settings: Exchange rate API credentials and base URL.
                      Falls back to ``get_settings().exchange_rate``.
            http_client: Optional pre-configured httpx.AsyncClient.
        """
        self._settings = settings or get_settings().exchange_rate
        self._client = http_client or httpx.AsyncClient(timeout=15.0)
        self._owns_client = http_client is None
        # Per-base-currency cache
        self._cache: dict[str, _CacheEntry] = {}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Close the underlying HTTP client if owned by this instance."""
        if self._owns_client and not self._client.is_closed:
            await self._client.aclose()

    async def __aenter__(self) -> "ExchangeRateClient":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:  # noqa: ANN001
        await self.close()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_cached(self, base: str) -> dict[str, Decimal] | None:
        """Return cached rates for *base* if present and not expired."""
        entry = self._cache.get(base)
        if entry is not None and not entry.is_expired():
            return entry.rates
        return None

    def _set_cache(self, base: str, rates: dict[str, Decimal]) -> None:
        """Store rates in the in-memory cache."""
        self._cache[base] = _CacheEntry(rates)

    async def _fetch_rates(self, base: str) -> dict[str, Decimal]:
        """
        Fetch live rates from the upstream API.

        Raises:
            APIError: On network or HTTP errors.
        """
        url = f"{self._settings.base_url}{base}"
        params: dict[str, str] = {}
        # Some providers require the key as a query param
        if self._settings.api_key:
            params["apikey"] = self._settings.api_key

        try:
            response = await self._client.get(url, params=params if params else None)
        except (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout) as exc:
            raise APIError(
                message=f"Exchange rate API network error: {exc}",
                api_name="exchange_rate",
                original_error=exc,
            ) from exc

        if response.status_code != 200:
            raise APIError(
                message=f"Exchange rate API error: HTTP {response.status_code}",
                api_name="exchange_rate",
                status_code=response.status_code,
                response_body=response.text,
            )

        data: dict[str, Any] = response.json()
        raw_rates = data.get("rates", data.get("conversion_rates", {}))

        rates: dict[str, Decimal] = {}
        for currency, value in raw_rates.items():
            try:
                rates[currency] = Decimal(str(value))
            except Exception:
                logger.warning("exchange_rate_parse_error", currency=currency, value=value)
                continue

        return rates

    def _fallback_rates(self, base: str) -> dict[str, Decimal]:
        """
        Compute fallback rates relative to *base* from the hardcoded USD table.

        If *base* is not in the fallback table the rates are returned as-is
        (effectively treating *base* as USD).
        """
        base_upper = base.upper()
        base_in_usd = FALLBACK_RATES.get(base_upper)

        if base_in_usd is None or base_in_usd == 0:
            logger.warning("exchange_rate_fallback_unknown_base", base=base_upper)
            return dict(FALLBACK_RATES)

        # Convert every currency so that 1 unit of *base* = X units of target
        converted: dict[str, Decimal] = {}
        for currency, usd_rate in FALLBACK_RATES.items():
            converted[currency] = (usd_rate / base_in_usd).quantize(Decimal("0.0001"))

        return converted

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_rates(self, base: str = "USD") -> dict[str, Decimal]:
        """
        Get exchange rates for all available currencies relative to *base*.

        Results are cached in memory for up to 1 hour.  If the upstream API
        is unreachable, hardcoded fallback rates are returned.

        Args:
            base: Base currency code (e.g. ``USD``, ``CNY``).

        Returns:
            Mapping of currency codes to their rate relative to *base*.
        """
        base_upper = base.upper()

        # 1. Try the cache
        cached = self._get_cached(base_upper)
        if cached is not None:
            logger.debug("exchange_rate_cache_hit", base=base_upper)
            return cached

        # 2. Fetch live rates
        try:
            rates = await self._fetch_rates(base_upper)
            self._set_cache(base_upper, rates)
            logger.info("exchange_rate_fetched", base=base_upper, count=len(rates))
            return rates
        except (APIError, Exception) as exc:
            logger.warning(
                "exchange_rate_fetch_failed_using_fallback",
                base=base_upper,
                error=str(exc),
            )
            fallback = self._fallback_rates(base_upper)
            # Cache fallback too (avoids hammering a down API)
            self._set_cache(base_upper, fallback)
            return fallback

    async def get_rate(self, base: str = "CNY", target: str = "KRW") -> Decimal:
        """
        Get the exchange rate from *base* to *target*.

        Args:
            base: Source currency code (default ``CNY``).
            target: Target currency code (default ``KRW``).

        Returns:
            Exchange rate as a ``Decimal`` (1 unit of *base* = N units of *target*).
        """
        rates = await self.get_rates(base)
        target_upper = target.upper()

        rate = rates.get(target_upper)
        if rate is not None:
            return rate

        # If the target is not in the rates dict, try to cross-calculate via USD
        logger.warning("exchange_rate_target_not_found_direct", base=base, target=target_upper)
        usd_rates = await self.get_rates("USD")
        base_in_usd = usd_rates.get(base.upper(), Decimal("1"))
        target_in_usd = usd_rates.get(target_upper, Decimal("1"))

        if base_in_usd == 0:
            return Decimal("0")

        cross_rate = (target_in_usd / base_in_usd).quantize(Decimal("0.0001"))
        return cross_rate
