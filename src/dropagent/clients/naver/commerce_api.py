"""
Naver Commerce API client.

Provides async methods for managing products and orders on the Naver
SmartStore Commerce platform.  All requests are signed using
``NaverCommerceAuth`` (HMAC-SHA256).  A Redis-backed token-bucket rate
limiter ensures compliance with Naver's API rate limits (2 req/s).

Reference:
    https://apicenter.commerce.naver.com/ko/basic/commerce-api
"""

import asyncio
from typing import Any

import httpx

from dropagent.config import NaverSettings, get_settings
from dropagent.core.rate_limiter import TokenBucketRateLimiter
from dropagent.utils.exceptions import APIError, RateLimitError
from dropagent.utils.logging import get_logger

from .auth import NaverCommerceAuth
from .models import NaverCommerceProduct

logger = get_logger(__name__)

COMMERCE_BASE_URL = "https://api.commerce.naver.com/external"

# Retry configuration
MAX_RETRIES = 3
INITIAL_BACKOFF = 1.0  # seconds
BACKOFF_MULTIPLIER = 2.0


class NaverCommerceClient:
    """
    Async client for the Naver Commerce (SmartStore) API.

    Every request is HMAC-signed and rate-limited through an
    ``AsyncRateLimiter`` instance (optional -- omit for environments
    without Redis).
    """

    def __init__(
        self,
        settings: NaverSettings | None = None,
        http_client: httpx.AsyncClient | None = None,
        rate_limiter: TokenBucketRateLimiter | None = None,
    ) -> None:
        """
        Args:
            settings: Naver API credentials.  Falls back to ``get_settings().naver``.
            http_client: Optional pre-configured httpx.AsyncClient.
            rate_limiter: Optional ``TokenBucketRateLimiter`` for enforcing rate limits.
        """
        self._settings = settings or get_settings().naver
        self._auth = NaverCommerceAuth(self._settings)
        self._client = http_client or httpx.AsyncClient(timeout=30.0)
        self._owns_client = http_client is None
        self._rate_limiter = rate_limiter

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Close the underlying HTTP client if owned by this instance."""
        if self._owns_client and not self._client.is_closed:
            await self._client.aclose()

    async def __aenter__(self) -> "NaverCommerceClient":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:  # noqa: ANN001
        await self.close()

    # ------------------------------------------------------------------
    # Internal rate-limited request method
    # ------------------------------------------------------------------

    async def _wait_for_rate_limit(self) -> None:
        """Wait until the token bucket permits a request (no-op if no limiter)."""
        if self._rate_limiter is None:
            return
        # ``acquire`` blocks until a token is available and raises
        # ``RateLimitError`` itself if the timeout elapses first.
        await self._rate_limiter.acquire(timeout=30.0)

    async def _request(
        self,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Execute an authenticated, rate-limited request to the Commerce API.

        Retries on transient server errors (5xx) and rate-limit (429) responses
        with exponential backoff.

        Args:
            method: HTTP method (``GET``, ``POST``, ``PUT``, ``DELETE``).
            path: API path relative to the base URL (e.g. ``/v2/products``).
            json_body: Optional JSON body payload.
            params: Optional URL query parameters.

        Returns:
            Parsed JSON response body.

        Raises:
            RateLimitError: On HTTP 429 after all retries.
            APIError: On any other non-successful response.
        """
        url = f"{COMMERCE_BASE_URL}{path}"
        last_error: Exception | None = None

        for attempt in range(MAX_RETRIES):
            # Wait for rate limiter token
            await self._wait_for_rate_limit()

            auth_headers = self._auth.get_auth_headers(method=method.upper(), path=path)
            headers = {
                "Content-Type": "application/json",
                **auth_headers,
            }

            try:
                response = await self._client.request(
                    method=method.upper(),
                    url=url,
                    headers=headers,
                    json=json_body,
                    params=params,
                )
            except (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout) as exc:
                last_error = exc
                logger.warning(
                    "naver_commerce_network_error",
                    error=str(exc),
                    attempt=attempt + 1,
                    path=path,
                )
                if attempt < MAX_RETRIES - 1:
                    backoff = INITIAL_BACKOFF * (BACKOFF_MULTIPLIER ** attempt)
                    await asyncio.sleep(backoff)
                    continue
                raise APIError(
                    message=f"Naver Commerce API network error after {MAX_RETRIES} retries: {exc}",
                    api_name="naver_commerce",
                    original_error=exc,
                ) from exc

            if response.status_code == 429:
                retry_after = int(response.headers.get("Retry-After", "1"))
                logger.warning(
                    "naver_commerce_rate_limit",
                    retry_after=retry_after,
                    attempt=attempt + 1,
                )
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(retry_after)
                    continue
                raise RateLimitError(
                    message="Naver Commerce API rate limit exceeded",
                    api_name="naver_commerce",
                    retry_after=retry_after,
                )

            if response.status_code >= 500:
                logger.warning(
                    "naver_commerce_server_error",
                    status_code=response.status_code,
                    attempt=attempt + 1,
                    path=path,
                )
                if attempt < MAX_RETRIES - 1:
                    backoff = INITIAL_BACKOFF * (BACKOFF_MULTIPLIER ** attempt)
                    await asyncio.sleep(backoff)
                    continue

            if response.status_code >= 400:
                raise APIError(
                    message=f"Naver Commerce API error: HTTP {response.status_code}",
                    api_name="naver_commerce",
                    status_code=response.status_code,
                    response_body=response.text,
                )

            # 204 No Content (e.g. successful DELETE)
            if response.status_code == 204:
                return {}

            return response.json()

        raise APIError(
            message=f"Naver Commerce API failed after {MAX_RETRIES} retries",
            api_name="naver_commerce",
            original_error=last_error,
        )

    # ------------------------------------------------------------------
    # Product management
    # ------------------------------------------------------------------

    async def register_product(self, product_data: dict[str, Any]) -> str:
        """
        Register a new product on Naver SmartStore.

        Args:
            product_data: Product payload conforming to Naver Commerce API schema.

        Returns:
            The newly created product ID (``smartStoreChannelProductId`` or
            ``channelProductId``).

        Raises:
            APIError: If registration fails.
        """
        logger.info("naver_commerce_register_product")
        path = "/v2/products"
        data = await self._request("POST", path, json_body=product_data)

        product_id = str(
            data.get("smartStoreChannelProductId", data.get("channelProductId", ""))
        )
        logger.info("naver_commerce_product_registered", product_id=product_id)
        return product_id

    async def update_product(self, product_id: str, product_data: dict[str, Any]) -> bool:
        """
        Update an existing product on Naver SmartStore.

        Args:
            product_id: The SmartStore channel product ID.
            product_data: Updated product payload.

        Returns:
            ``True`` if the update succeeded.

        Raises:
            APIError: If the update fails.
        """
        logger.info("naver_commerce_update_product", product_id=product_id)
        path = f"/v2/products/{product_id}"
        await self._request("PUT", path, json_body=product_data)
        logger.info("naver_commerce_product_updated", product_id=product_id)
        return True

    async def delete_product(self, product_id: str) -> bool:
        """
        Delete a product from Naver SmartStore.

        Args:
            product_id: The SmartStore channel product ID.

        Returns:
            ``True`` if the deletion succeeded.

        Raises:
            APIError: If the deletion fails.
        """
        logger.info("naver_commerce_delete_product", product_id=product_id)
        path = f"/v2/products/{product_id}"
        await self._request("DELETE", path)
        logger.info("naver_commerce_product_deleted", product_id=product_id)
        return True

    async def get_product(self, product_id: str) -> NaverCommerceProduct:
        """
        Retrieve a single product from Naver SmartStore.

        Args:
            product_id: The SmartStore channel product ID.

        Returns:
            ``NaverCommerceProduct`` model.

        Raises:
            APIError: If the product cannot be fetched.
        """
        logger.info("naver_commerce_get_product", product_id=product_id)
        path = f"/v2/products/{product_id}"
        data = await self._request("GET", path)
        return NaverCommerceProduct.model_validate(data)

    # ------------------------------------------------------------------
    # Order management
    # ------------------------------------------------------------------

    async def get_orders(
        self,
        status: str | None = None,
        from_date: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Retrieve seller orders from Naver Commerce.

        Args:
            status: Optional order status filter
                    (e.g. ``PAYED``, ``DELIVERING``, ``DELIVERED``).
            from_date: Optional start date filter (ISO 8601, e.g. ``2024-01-01``).

        Returns:
            List of raw order dictionaries.

        Raises:
            APIError: If the request fails.
        """
        logger.info("naver_commerce_get_orders", status=status, from_date=from_date)
        path = "/v1/pay-order/seller/orders"

        params: dict[str, Any] = {}
        if status is not None:
            params["orderStatus"] = status
        if from_date is not None:
            params["fromDate"] = from_date

        data = await self._request("GET", path, params=params)

        orders = data.get("data", data.get("orders", []))
        if isinstance(orders, dict):
            orders = [orders]

        logger.info("naver_commerce_orders_fetched", count=len(orders))
        return orders
