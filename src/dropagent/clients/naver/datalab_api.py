"""
Naver DataLab Shopping Insight API client.

Provides async methods for retrieving shopping search trends and keyword
insights from Naver DataLab, useful for market analysis and demand estimation.

Reference:
    https://developers.naver.com/docs/serviceapi/datalab/shopping/shopping.md
"""

from typing import Any

import httpx

from dropagent.config import NaverSettings, get_settings
from dropagent.utils.exceptions import APIError, RateLimitError
from dropagent.utils.logging import get_logger

from .auth import NaverAuth
from .models import NaverTrendGroup, NaverTrendItem, NaverTrendResult

logger = get_logger(__name__)

DATALAB_SHOPPING_URL = "https://openapi.naver.com/v1/datalab/shopping"
DATALAB_CATEGORY_KEYWORDS_URL = "https://openapi.naver.com/v1/datalab/shopping/category/keywords"


class NaverDataLabClient:
    """
    Async client for the Naver DataLab Shopping Insight API.

    Authenticates via ``X-Naver-Client-Id`` / ``X-Naver-Client-Secret``
    headers (same mechanism as the Shopping Search API).
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

    async def __aenter__(self) -> "NaverDataLabClient":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:  # noqa: ANN001
        await self.close()

    # ------------------------------------------------------------------
    # Internal helper
    # ------------------------------------------------------------------

    async def _post(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        """
        Execute a POST request to a DataLab endpoint.

        Raises:
            RateLimitError: On HTTP 429.
            APIError: On any other non-200 response.
        """
        headers = {
            "Content-Type": "application/json",
            **self._auth.get_auth_headers(),
        }

        try:
            response = await self._client.post(url, json=payload, headers=headers)
        except (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout) as exc:
            raise APIError(
                message=f"Naver DataLab API network error: {exc}",
                api_name="naver_datalab",
                original_error=exc,
            ) from exc

        if response.status_code == 429:
            retry_after = int(response.headers.get("Retry-After", "1"))
            raise RateLimitError(
                message="Naver DataLab API rate limit exceeded",
                api_name="naver_datalab",
                retry_after=retry_after,
            )

        if response.status_code != 200:
            raise APIError(
                message=f"Naver DataLab API error: HTTP {response.status_code}",
                api_name="naver_datalab",
                status_code=response.status_code,
                response_body=response.text,
            )

        return response.json()

    # ------------------------------------------------------------------
    # Response parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_trend_result(
        data: dict[str, Any],
        start_date: str,
        end_date: str,
    ) -> NaverTrendResult:
        """Parse the raw DataLab response into a ``NaverTrendResult``."""
        groups: list[NaverTrendGroup] = []
        for result in data.get("results", []):
            title = result.get("title", "")
            keywords = result.get("keyword", [])
            if isinstance(keywords, str):
                keywords = [keywords]

            items: list[NaverTrendItem] = []
            for point in result.get("data", []):
                items.append(
                    NaverTrendItem(
                        period=point.get("period", ""),
                        ratio=float(point.get("ratio", 0.0)),
                        group=title,
                    )
                )
            groups.append(NaverTrendGroup(title=title, keywords=keywords, data=items))

        return NaverTrendResult(results=groups, start_date=start_date, end_date=end_date)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_shopping_trend(
        self,
        keyword: str,
        category: str,
        start_date: str,
        end_date: str,
        time_unit: str = "month",
    ) -> NaverTrendResult:
        """
        Retrieve the shopping search trend for a keyword within a category.

        Args:
            keyword: Search keyword to track.
            category: Naver DataLab shopping category code.
            start_date: Start date (``YYYY-MM-DD``).
            end_date: End date (``YYYY-MM-DD``).
            time_unit: Aggregation unit -- ``date``, ``week``, or ``month``.

        Returns:
            ``NaverTrendResult`` with trend data.
        """
        logger.info(
            "naver_datalab_shopping_trend",
            keyword=keyword,
            category=category,
            start_date=start_date,
            end_date=end_date,
        )

        payload: dict[str, Any] = {
            "startDate": start_date,
            "endDate": end_date,
            "timeUnit": time_unit,
            "category": category,
            "keyword": [{"name": keyword, "param": [keyword]}],
        }

        data = await self._post(DATALAB_SHOPPING_URL, payload)
        return self._parse_trend_result(data, start_date, end_date)

    async def get_category_keywords(
        self,
        category: str,
        top_n: int = 500,
    ) -> list[dict[str, Any]]:
        """
        Retrieve popular keywords for a shopping category.

        Args:
            category: Naver DataLab shopping category code.
            top_n: Number of top keywords to return (max 500).

        Returns:
            List of keyword dictionaries (``{"keyword": ..., "count": ...}``).
        """
        logger.info("naver_datalab_category_keywords", category=category, top_n=top_n)

        payload: dict[str, Any] = {
            "category": category,
            "count": min(top_n, 500),
        }

        data = await self._post(DATALAB_CATEGORY_KEYWORDS_URL, payload)

        keywords = data.get("results", [])
        if isinstance(keywords, dict):
            keywords = [keywords]

        return keywords[:top_n]

    async def get_keyword_trend(
        self,
        keywords: list[str],
        start_date: str,
        end_date: str,
        time_unit: str = "month",
    ) -> NaverTrendResult:
        """
        Compare search trends for multiple keywords.

        Each keyword is submitted as its own group so that their relative
        popularity can be compared side by side.

        Args:
            keywords: List of keywords to compare (max 5).
            start_date: Start date (``YYYY-MM-DD``).
            end_date: End date (``YYYY-MM-DD``).
            time_unit: Aggregation unit -- ``date``, ``week``, or ``month``.

        Returns:
            ``NaverTrendResult`` with one group per keyword.
        """
        logger.info(
            "naver_datalab_keyword_trend",
            keywords=keywords,
            start_date=start_date,
            end_date=end_date,
        )

        # Each keyword becomes its own group for side-by-side comparison
        keyword_groups = [
            {"name": kw, "param": [kw]}
            for kw in keywords[:5]  # API supports max 5 groups
        ]

        payload: dict[str, Any] = {
            "startDate": start_date,
            "endDate": end_date,
            "timeUnit": time_unit,
            "keyword": keyword_groups,
        }

        data = await self._post(DATALAB_SHOPPING_URL, payload)
        return self._parse_trend_result(data, start_date, end_date)
