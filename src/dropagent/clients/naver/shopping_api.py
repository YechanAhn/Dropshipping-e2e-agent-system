"""
Naver Shopping Search API client.

Provides async methods for querying the Naver Shopping catalogue, including
basic search, paginated search, and a convenience method to extract competitor
price information for a given product query.

Reference:
    https://developers.naver.com/docs/serviceapi/search/shopping/shopping.md
"""

import asyncio
from dataclasses import dataclass, field
from typing import Any

import httpx

from dropagent.config import NaverSettings, get_settings
from dropagent.utils.exceptions import APIError, RateLimitError
from dropagent.utils.logging import get_logger

from .auth import NaverAuth
from .models import NaverShoppingItem, NaverShoppingResult

logger = get_logger(__name__)

SHOPPING_SEARCH_URL = "https://openapi.naver.com/v1/search/shop.json"


@dataclass
class CatalogLowest:
    """A keyword's live lowest-price snapshot from the Naver Shopping API.

    Attributes:
        lowest_price: Cheapest lprice across all results (incl. 단독 sellers) -- the
            true market floor a listing competes against.
        catalog_parent_price: Cheapest lprice among 가격비교 대표(catalog parent)
            items = the 최저가 badge price. ``None`` when no catalog is present.
        has_catalog: Whether any 가격비교 대표 item appeared.
        mall_name: Mall name of the lowest-priced item (who currently holds it).
        product_type: productType of the lowest-priced item.
        sample: The (sorted asc) lprice sample used, for transparency/debugging.
        total: Total result count reported by the API.
    """

    lowest_price: int = 0
    catalog_parent_price: int | None = None
    has_catalog: bool = False
    mall_name: str = ""
    product_type: int = 0
    sample: list[int] = field(default_factory=list)
    total: int = 0

# Maximum items per request imposed by the Naver Search API
MAX_DISPLAY = 100
# Maximum reachable offset (start + display - 1 must be <= 1100)
MAX_START = 1000


class NaverShoppingClient:
    """
    Async client for the Naver Shopping Search API.

    Authenticates via simple ``X-Naver-Client-Id`` / ``X-Naver-Client-Secret``
    headers (see ``NaverAuth``).
    """

    def __init__(
        self,
        settings: NaverSettings | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        """
        Args:
            settings: Naver API credentials.  Falls back to ``get_settings().naver``.
            http_client: Optional pre-configured httpx.AsyncClient.
        """
        self._settings = settings or get_settings().naver
        self._auth = NaverAuth(self._settings)
        self._client = http_client or httpx.AsyncClient(timeout=15.0)
        self._owns_client = http_client is None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Close the underlying HTTP client if owned by this instance."""
        if self._owns_client and not self._client.is_closed:
            await self._client.aclose()

    async def __aenter__(self) -> "NaverShoppingClient":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:  # noqa: ANN001
        await self.close()

    # ------------------------------------------------------------------
    # Internal helper
    # ------------------------------------------------------------------

    async def _get(self, params: dict[str, Any]) -> dict[str, Any]:
        """
        Execute a GET request to the Naver Shopping Search endpoint.

        Raises:
            RateLimitError: On HTTP 429.
            APIError: On any other non-200 response.
        """
        headers = self._auth.get_auth_headers()
        try:
            response = await self._client.get(
                SHOPPING_SEARCH_URL,
                params=params,
                headers=headers,
            )
        except (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout) as exc:
            raise APIError(
                message=f"Naver Shopping API network error: {exc}",
                api_name="naver_shopping",
                original_error=exc,
            ) from exc

        if response.status_code == 429:
            retry_after = int(response.headers.get("Retry-After", "1"))
            raise RateLimitError(
                message="Naver Shopping API rate limit exceeded",
                api_name="naver_shopping",
                retry_after=retry_after,
            )

        if response.status_code != 200:
            raise APIError(
                message=f"Naver Shopping API error: HTTP {response.status_code}",
                api_name="naver_shopping",
                status_code=response.status_code,
                response_body=response.text,
            )

        return response.json()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def search(
        self,
        query: str,
        display: int = 10,
        start: int = 1,
        sort: str = "sim",
    ) -> NaverShoppingResult:
        """
        Search for products on Naver Shopping.

        Args:
            query: Search keywords.
            display: Number of results to return (1-100, default 10).
            start: Starting position of the results (1-based, max 1000).
            sort: Sort order -- ``sim`` (relevance), ``date``, ``asc`` (price low),
                  ``dsc`` (price high).

        Returns:
            ``NaverShoppingResult`` with matched items and pagination metadata.
        """
        logger.info("naver_shopping_search", query=query, display=display, start=start, sort=sort)

        params: dict[str, Any] = {
            "query": query,
            "display": min(display, MAX_DISPLAY),
            "start": min(start, MAX_START),
            "sort": sort,
        }

        data = await self._get(params)

        items = [NaverShoppingItem.model_validate(item) for item in data.get("items", [])]

        return NaverShoppingResult(
            items=items,
            total=int(data.get("total", 0)),
            start=int(data.get("start", start)),
            display=int(data.get("display", display)),
        )

    async def get_competitor_prices(self, query: str, top_n: int = 10) -> list[int]:
        """
        Retrieve the lowest prices from the top-N search results for *query*.

        This is a convenience wrapper that extracts ``lowest_price`` from each
        result item and filters out zero values.

        Args:
            query: Product search query.
            top_n: Number of results to consider (max 100).

        Returns:
            Sorted list of prices in KRW (ascending).
        """
        logger.info("naver_competitor_prices", query=query, top_n=top_n)

        result = await self.search(query=query, display=min(top_n, MAX_DISPLAY), sort="sim")
        prices = [item.lowest_price for item in result.items if item.lowest_price > 0]
        prices.sort()
        return prices

    async def get_catalog_lowest(self, query: str, *, display: int = 40) -> CatalogLowest:
        """Fetch the live lowest price for *query* in a single ``sort=asc`` call.

        Used by the repricer where freshness matters. The first item (cheapest)
        gives the market floor; the cheapest 가격비교 대표 item gives the catalog
        최저가 badge price a new seller must match for exposure.

        Args:
            query: Product/keyword to look up.
            display: Number of results to scan (max 100). 40 is plenty to find
                both the overall floor and the catalog parent.

        Returns:
            ``CatalogLowest`` snapshot (all-zero/empty when there are no results).
        """
        logger.info("naver_catalog_lowest", query=query, display=display)

        result = await self.search(query=query, display=min(display, MAX_DISPLAY), sort="asc")
        priced = [it for it in result.items if it.lowest_price > 0]
        if not priced:
            return CatalogLowest(total=result.total)

        # sort=asc already orders by price, but re-sort defensively.
        priced.sort(key=lambda it: it.lowest_price)
        cheapest = priced[0]
        catalog_prices = [it.lowest_price for it in priced if it.is_catalog]

        return CatalogLowest(
            lowest_price=cheapest.lowest_price,
            catalog_parent_price=min(catalog_prices) if catalog_prices else None,
            has_catalog=bool(catalog_prices),
            mall_name=cheapest.mall_name,
            product_type=cheapest.product_type,
            sample=[it.lowest_price for it in priced[:10]],
            total=result.total,
        )

    async def search_with_pagination(
        self,
        query: str,
        total: int = 100,
    ) -> list[NaverShoppingItem]:
        """
        Collect up to *total* search results by paginating automatically.

        The Naver Search API caps at ``start + display - 1 <= 1100``, so the
        effective maximum is 1100 items.

        Args:
            query: Search keywords.
            total: Desired number of results (capped at API limit).

        Returns:
            Aggregated list of ``NaverShoppingItem`` instances.
        """
        logger.info("naver_shopping_paginated_search", query=query, requested_total=total)

        collected: list[NaverShoppingItem] = []
        page_size = min(total, MAX_DISPLAY)
        start = 1

        while len(collected) < total and start <= MAX_START:
            remaining = total - len(collected)
            display = min(remaining, page_size, MAX_DISPLAY)

            result = await self.search(query=query, display=display, start=start)

            if not result.items:
                break

            collected.extend(result.items)

            # If the API returned fewer items than requested, we have reached the end
            if len(result.items) < display:
                break

            start += display

            # Small delay to be polite to the API
            await asyncio.sleep(0.1)

        logger.info("naver_shopping_paginated_done", query=query, total_collected=len(collected))
        return collected
