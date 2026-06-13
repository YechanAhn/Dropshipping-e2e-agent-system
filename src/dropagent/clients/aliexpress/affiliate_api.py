"""
AliExpress Affiliate API client.

Implements the AliExpress TOP protocol for the Affiliate API, including
HMAC-SHA256 request signing, search, product detail retrieval, and hot
product listing.  All HTTP traffic uses httpx.AsyncClient with automatic
retry and exponential backoff for transient errors and rate limits.

Reference:
    https://portals.aliexpress.com/affiapi/doc
"""

import asyncio
import hashlib
import hmac
import time
from decimal import Decimal
from typing import Any

import httpx

from dropagent.config import AliExpressSettings, get_settings
from dropagent.utils.exceptions import APIError, RateLimitError
from dropagent.utils.logging import get_logger

from .models import (
    AliPriceInfo,
    AliProduct,
    AliProductDetail,
    AliProductVariant,
    AliSearchResult,
    AliSellerInfo,
    AliShippingInfo,
)

logger = get_logger(__name__)

BASE_URL = "https://api-sg.aliexpress.com/sync"

# Retry configuration
MAX_RETRIES = 3
INITIAL_BACKOFF = 1.0  # seconds
BACKOFF_MULTIPLIER = 2.0


class AliExpressAffiliateClient:
    """
    Async client for the AliExpress Affiliate API.

    Uses the standard AliExpress TOP protocol with HMAC-SHA256 signing.
    Handles rate-limit (HTTP 429) responses and transient errors with
    exponential backoff retries (up to ``MAX_RETRIES`` attempts).
    """

    def __init__(
        self,
        settings: AliExpressSettings | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        """
        Args:
            settings: AliExpress API credentials.  Falls back to ``get_settings().aliexpress``.
            http_client: Optional pre-configured httpx.AsyncClient (useful for testing).
        """
        self._settings = settings or get_settings().aliexpress
        self._client = http_client or httpx.AsyncClient(timeout=30.0)
        self._owns_client = http_client is None

    # ------------------------------------------------------------------
    # Lifecycle helpers
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Close the underlying HTTP client if we own it."""
        if self._owns_client and not self._client.is_closed:
            await self._client.aclose()

    async def __aenter__(self) -> "AliExpressAffiliateClient":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:  # noqa: ANN001
        await self.close()

    # ------------------------------------------------------------------
    # Request signing (AliExpress TOP protocol)
    # ------------------------------------------------------------------

    def _sign_request(self, api_name: str, params: dict[str, str]) -> str:
        """
        Compute the HMAC-SHA256 signature for an AliExpress TOP API call.

        The TOP protocol concatenates the API name with all sorted
        key-value pairs, then HMAC-SHA256 signs the result using the
        app secret.

        Args:
            api_name: Full API method name (e.g. ``aliexpress.affiliate.product.query``).
            params: Request parameters *excluding* ``sign`` itself.

        Returns:
            Uppercase hex-encoded HMAC-SHA256 signature.
        """
        # Sort parameters alphabetically by key
        sorted_params = sorted(params.items())
        # Build the sign string: api_name + key1value1key2value2...
        sign_str = api_name
        for key, value in sorted_params:
            sign_str += f"{key}{value}"

        # HMAC-SHA256 with app_secret as key
        signature = hmac.new(
            self._settings.app_secret.encode("utf-8"),
            sign_str.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest().upper()

        return signature

    def _build_common_params(self, api_name: str) -> dict[str, str]:
        """Build the common TOP protocol request parameters."""
        return {
            "app_key": self._settings.app_key,
            "timestamp": str(int(time.time() * 1000)),
            "sign_method": "sha256",
            "method": api_name,
            "v": "2.0",
            "format": "json",
        }

    # ------------------------------------------------------------------
    # Internal HTTP helper with retry logic
    # ------------------------------------------------------------------

    async def _request(self, api_name: str, business_params: dict[str, Any]) -> dict[str, Any]:
        """
        Execute a signed API request with retry and exponential backoff.

        Args:
            api_name: AliExpress TOP API method name.
            business_params: Business-specific parameters for the API call.

        Returns:
            Parsed JSON response body (the inner result object).

        Raises:
            RateLimitError: If the server returns HTTP 429 after all retries.
            APIError: For any other non-successful HTTP response or API error.
        """
        params = self._build_common_params(api_name)
        # Add business parameters (stringify all values for signing)
        for key, value in business_params.items():
            if value is not None:
                params[key] = str(value)

        # Compute signature
        params["sign"] = self._sign_request(api_name, params)

        last_error: Exception | None = None

        for attempt in range(MAX_RETRIES):
            try:
                response = await self._client.post(
                    BASE_URL,
                    data=params,
                    headers={"Content-Type": "application/x-www-form-urlencoded;charset=utf-8"},
                )

                if response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", "1"))
                    logger.warning(
                        "aliexpress_rate_limit",
                        attempt=attempt + 1,
                        retry_after=retry_after,
                    )
                    if attempt < MAX_RETRIES - 1:
                        await asyncio.sleep(retry_after)
                        continue
                    raise RateLimitError(
                        message="AliExpress API rate limit exceeded",
                        api_name="aliexpress",
                        retry_after=retry_after,
                    )

                if response.status_code >= 500:
                    logger.warning(
                        "aliexpress_server_error",
                        status_code=response.status_code,
                        attempt=attempt + 1,
                    )
                    if attempt < MAX_RETRIES - 1:
                        backoff = INITIAL_BACKOFF * (BACKOFF_MULTIPLIER ** attempt)
                        await asyncio.sleep(backoff)
                        continue

                if response.status_code != 200:
                    raise APIError(
                        message=f"AliExpress API error: HTTP {response.status_code}",
                        api_name="aliexpress",
                        status_code=response.status_code,
                        response_body=response.text,
                    )

                data = response.json()

                # TOP protocol wraps errors in an ``error_response`` object
                if "error_response" in data:
                    error = data["error_response"]
                    error_code = error.get("code", "unknown")
                    error_msg = error.get("msg", "Unknown AliExpress API error")
                    raise APIError(
                        message=f"AliExpress API error [{error_code}]: {error_msg}",
                        api_name="aliexpress",
                        response_body=str(error),
                    )

                return data

            except (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout) as exc:
                last_error = exc
                logger.warning(
                    "aliexpress_network_error",
                    error=str(exc),
                    attempt=attempt + 1,
                )
                if attempt < MAX_RETRIES - 1:
                    backoff = INITIAL_BACKOFF * (BACKOFF_MULTIPLIER ** attempt)
                    await asyncio.sleep(backoff)
                    continue
                raise APIError(
                    message=f"AliExpress API network error after {MAX_RETRIES} retries: {exc}",
                    api_name="aliexpress",
                    original_error=exc,
                ) from exc

        # Should not be reached but satisfies the type checker
        raise APIError(
            message=f"AliExpress API failed after {MAX_RETRIES} retries",
            api_name="aliexpress",
            original_error=last_error,
        )

    # ------------------------------------------------------------------
    # Response parsing helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_product(raw: dict[str, Any]) -> AliProduct:
        """Parse a single raw product dict into an ``AliProduct`` model."""
        price = AliPriceInfo(
            original_price=Decimal(str(raw.get("original_price", "0"))),
            sale_price=Decimal(str(raw.get("target_sale_price", raw.get("sale_price", "0")))),
        )
        shipping = AliShippingInfo(
            days=int(raw.get("ship_to_days", raw.get("logistics_info", {}).get("days", 0))),
            cost=Decimal(str(raw.get("shipping_cost", "0"))),
        )
        seller = AliSellerInfo(
            id=str(raw.get("seller_id", raw.get("shop_id", ""))),
            rating=Decimal(str(raw.get("seller_rating", raw.get("evaluate_rate", "0")))),
            name=raw.get("shop_name", raw.get("seller_name", "")),
        )
        return AliProduct(
            product_id=str(raw.get("product_id", "")),
            title=raw.get("product_title", raw.get("product_name", "")),
            price=price,
            currency=raw.get("target_sale_price_currency", raw.get("currency", "USD")),
            category_id=str(raw.get("first_level_category_id", "")) or None,
            category_name=raw.get("first_level_category_name") or None,
            image_url=raw.get("product_main_image_url", ""),
            product_url=raw.get("promotion_link", raw.get("product_detail_url", "")),
            rating=Decimal(str(raw.get("evaluate_rate", raw.get("product_rating", "0")))),
            order_count=int(raw.get("lastest_volume", raw.get("order_count", 0))),
            shipping_info=shipping,
            seller_info=seller,
        )

    @staticmethod
    def _parse_product_detail(raw: dict[str, Any]) -> AliProductDetail:
        """Parse a single raw product dict into an ``AliProductDetail`` model."""
        price = AliPriceInfo(
            original_price=Decimal(str(raw.get("original_price", "0"))),
            sale_price=Decimal(str(raw.get("target_sale_price", raw.get("sale_price", "0")))),
        )
        shipping = AliShippingInfo(
            days=int(raw.get("ship_to_days", raw.get("logistics_info", {}).get("days", 0))),
            cost=Decimal(str(raw.get("shipping_cost", "0"))),
        )
        seller = AliSellerInfo(
            id=str(raw.get("seller_id", raw.get("shop_id", ""))),
            rating=Decimal(str(raw.get("seller_rating", raw.get("evaluate_rate", "0")))),
            name=raw.get("shop_name", raw.get("seller_name", "")),
        )

        # Parse variants / SKU options
        variants: list[AliProductVariant] = []
        sku_list = raw.get("sku_info", raw.get("product_sku_list", []))
        if isinstance(sku_list, list):
            for sku in sku_list:
                variants.append(
                    AliProductVariant(
                        sku_id=str(sku.get("sku_id", "")),
                        name=sku.get("sku_attr", sku.get("name", "")),
                        value=sku.get("sku_val", sku.get("value", "")),
                        image_url=sku.get("sku_image") or None,
                        price=Decimal(str(sku["offer_sale_price"])) if "offer_sale_price" in sku else None,
                        stock=int(sku["sku_available_stock"]) if "sku_available_stock" in sku else None,
                    )
                )

        return AliProductDetail(
            product_id=str(raw.get("product_id", "")),
            title=raw.get("product_title", raw.get("product_name", "")),
            price=price,
            currency=raw.get("target_sale_price_currency", raw.get("currency", "USD")),
            category_id=str(raw.get("first_level_category_id", "")) or None,
            category_name=raw.get("first_level_category_name") or None,
            image_url=raw.get("product_main_image_url", ""),
            product_url=raw.get("promotion_link", raw.get("product_detail_url", "")),
            rating=Decimal(str(raw.get("evaluate_rate", raw.get("product_rating", "0")))),
            order_count=int(raw.get("lastest_volume", raw.get("order_count", 0))),
            shipping_info=shipping,
            seller_info=seller,
            description=raw.get("product_description", raw.get("description", "")),
            options=variants,
            reviews_count=int(raw.get("evaluate_num", raw.get("reviews_count", 0))),
        )

    # ------------------------------------------------------------------
    # Public API methods
    # ------------------------------------------------------------------

    async def search_products(
        self,
        keywords: str,
        category_id: str | None = None,
        min_price: float | None = None,
        max_price: float | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> AliSearchResult:
        """
        Search for affiliate products on AliExpress.

        Args:
            keywords: Search query keywords.
            category_id: Optional category filter.
            min_price: Minimum sale price filter (USD).
            max_price: Maximum sale price filter (USD).
            page: Result page number (1-based).
            page_size: Number of products per page (max 50).

        Returns:
            ``AliSearchResult`` containing matching products.
        """
        logger.info("aliexpress_search", keywords=keywords, page=page, page_size=page_size)

        business_params: dict[str, Any] = {
            "keywords": keywords,
            "page_no": page,
            "page_size": min(page_size, 50),
            "tracking_id": self._settings.tracking_id,
            "target_currency": self._settings.target_currency,
            "target_language": self._settings.target_language,
            "sort": "SALE_PRICE_ASC",
        }
        if category_id is not None:
            business_params["category_ids"] = category_id
        if min_price is not None:
            business_params["min_sale_price"] = str(min_price)
        if max_price is not None:
            business_params["max_sale_price"] = str(max_price)

        api_name = "aliexpress.affiliate.product.query"
        data = await self._request(api_name, business_params)

        # Navigate the nested response envelope
        resp = (
            data.get("aliexpress_affiliate_product_query_response", {})
            .get("resp_result", {})
        )
        result_data = resp.get("result", {})
        raw_products = result_data.get("products", {}).get("product", [])
        if isinstance(raw_products, dict):
            raw_products = [raw_products]

        products = [self._parse_product(p) for p in raw_products]

        return AliSearchResult(
            products=products,
            total_count=int(result_data.get("total_record_count", len(products))),
            current_page=int(result_data.get("current_page_no", page)),
        )

    async def get_product_detail(self, product_ids: list[str]) -> list[AliProductDetail]:
        """
        Retrieve detailed information for one or more products.

        Args:
            product_ids: List of AliExpress product IDs (max 20 per call).

        Returns:
            List of ``AliProductDetail`` models.
        """
        if not product_ids:
            return []

        logger.info("aliexpress_product_detail", product_count=len(product_ids))

        business_params: dict[str, Any] = {
            "product_ids": ",".join(product_ids[:20]),
            "tracking_id": self._settings.tracking_id,
            "target_currency": self._settings.target_currency,
            "target_language": self._settings.target_language,
        }

        api_name = "aliexpress.affiliate.productdetail.get"
        data = await self._request(api_name, business_params)

        resp = (
            data.get("aliexpress_affiliate_productdetail_get_response", {})
            .get("resp_result", {})
        )
        result_data = resp.get("result", {})
        raw_products = result_data.get("products", {}).get("product", [])
        if isinstance(raw_products, dict):
            raw_products = [raw_products]

        return [self._parse_product_detail(p) for p in raw_products]

    async def get_hot_products(
        self,
        category_id: str,
        page: int = 1,
    ) -> AliSearchResult:
        """
        Retrieve hot/trending products for a given category.

        Args:
            category_id: AliExpress category ID.
            page: Result page number (1-based).

        Returns:
            ``AliSearchResult`` containing hot products.
        """
        logger.info("aliexpress_hot_products", category_id=category_id, page=page)

        business_params: dict[str, Any] = {
            "category_ids": category_id,
            "page_no": page,
            "page_size": 50,
            "tracking_id": self._settings.tracking_id,
            "target_currency": self._settings.target_currency,
            "target_language": self._settings.target_language,
        }

        api_name = "aliexpress.affiliate.hotproduct.query"
        data = await self._request(api_name, business_params)

        resp = (
            data.get("aliexpress_affiliate_hotproduct_query_response", {})
            .get("resp_result", {})
        )
        result_data = resp.get("result", {})
        raw_products = result_data.get("products", {}).get("product", [])
        if isinstance(raw_products, dict):
            raw_products = [raw_products]

        products = [self._parse_product(p) for p in raw_products]

        return AliSearchResult(
            products=products,
            total_count=int(result_data.get("total_record_count", len(products))),
            current_page=int(result_data.get("current_page_no", page)),
        )
