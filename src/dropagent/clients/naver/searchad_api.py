"""
Naver Search Ad (검색광고) Keyword Tool client.

The Keyword Tool (``/keywordstool``, RelKwdStat) is the **only** source of
*absolute* monthly search volume on Naver. Given up to 5 seed ("hint")
keywords it returns related keywords, each with absolute monthly PC / mobile
search counts, average ad clicks, click-through-rate, and an ad competition
index. This is the spine of the demand-first discovery pipeline (see
``docs/RESEARCH_discovery.md`` §1.1).

Two gotchas this module handles explicitly:

1. **"< 10" masking** -- for low-volume keywords Naver returns the *string*
   ``"< 10"`` instead of an integer. ``parse_count`` converts it to a
   configurable sentinel (default 5) and flags it via ``is_masked``.
2. **Rate limiting** -- the keyword tool is throttled to roughly 1/5--1/6 the
   rate of other operations and measured per customer-id *and* client IP;
   exceeding it returns HTTP 429. We pace requests through a conservative
   in-process ``TokenBucketRateLimiter`` and back off on 429.
"""

import asyncio
from typing import Any

import httpx
from pydantic import BaseModel, Field

from dropagent.config import NaverSearchAdSettings, get_settings
from dropagent.core.rate_limiter import TokenBucketRateLimiter
from dropagent.utils.exceptions import APIError, RateLimitError
from dropagent.utils.logging import get_logger

from .auth import NaverSearchAdAuth

logger = get_logger(__name__)

SEARCHAD_BASE_URL = "https://api.searchad.naver.com"
KEYWORDSTOOL_PATH = "/keywordstool"

# The keyword tool accepts at most 5 hint keywords per call.
MAX_HINT_KEYWORDS = 5

# Sentinel used when Naver masks a count as the string "< 10".
MASKED_COUNT_VALUE = 5

# Retry configuration
MAX_RETRIES = 3
INITIAL_BACKOFF = 1.0
BACKOFF_MULTIPLIER = 2.0

# Conservative throttle for the keyword tool (it is rate-limited well below
# other operations). ~2 req/s sustained with a small burst.
KEYWORDSTOOL_RATE = 2.0
KEYWORDSTOOL_CAPACITY = 5


def parse_count(value: Any) -> tuple[int, bool]:
    """
    Parse a Naver Search Ad count field into ``(value, is_masked)``.

    Naver returns most counts as integers (or numeric strings), but masks
    low-volume keywords as the literal string ``"< 10"``. This helper maps
    that mask to ``MASKED_COUNT_VALUE`` and reports whether masking occurred.

    Args:
        value: Raw field value (int, numeric string, or ``"< 10"``).

    Returns:
        Tuple of the integer count and a flag indicating it was masked.
    """
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("<"):
            return MASKED_COUNT_VALUE, True
        # Numeric strings may contain separators or decimals.
        try:
            return int(float(stripped.replace(",", ""))), False
        except ValueError:
            return 0, False
    if isinstance(value, (int, float)):
        return int(value), False
    return 0, False


class KeywordStat(BaseModel):
    """Absolute search-volume statistics for a single keyword."""

    keyword: str = Field(description="Related keyword (relKeyword)")
    monthly_pc: int = Field(default=0, description="Monthly PC search count")
    monthly_mobile: int = Field(default=0, description="Monthly mobile search count")
    monthly_ave_pc_clicks: float = Field(default=0.0)
    monthly_ave_mobile_clicks: float = Field(default=0.0)
    monthly_ave_pc_ctr: float = Field(default=0.0)
    monthly_ave_mobile_ctr: float = Field(default=0.0)
    pl_avg_depth: int = Field(default=0, description="Avg number of ads shown")
    comp_idx: str = Field(default="", description="Ad competition: 낮음/중간/높음")
    is_masked: bool = Field(
        default=False,
        description="True if PC/mobile counts were masked as '< 10' by Naver",
    )

    @property
    def monthly_total(self) -> int:
        """Total monthly search volume (PC + mobile) -- the demand signal."""
        return self.monthly_pc + self.monthly_mobile


class NaverSearchAdClient:
    """
    Async client for the Naver Search Ad Keyword Tool.

    Example:
        >>> async with NaverSearchAdClient() as client:
        ...     stats = await client.get_keyword_stats(["무선 이어폰"])
        ...     for s in stats:
        ...         print(s.keyword, s.monthly_total)
    """

    def __init__(
        self,
        settings: NaverSearchAdSettings | None = None,
        http_client: httpx.AsyncClient | None = None,
        rate_limiter: TokenBucketRateLimiter | None = None,
    ) -> None:
        """
        Args:
            settings: Search Ad credentials. Falls back to ``get_settings().searchad``.
            http_client: Optional pre-configured httpx.AsyncClient (useful for testing).
            rate_limiter: Optional limiter. Defaults to a conservative keyword-tool bucket.
        """
        self._settings = settings or get_settings().searchad
        self._auth = NaverSearchAdAuth(self._settings)
        self._client = http_client or httpx.AsyncClient(timeout=15.0)
        self._owns_client = http_client is None
        self._rate_limiter = rate_limiter or TokenBucketRateLimiter(
            rate=KEYWORDSTOOL_RATE,
            capacity=KEYWORDSTOOL_CAPACITY,
            name="naver_searchad_keywordstool",
        )

    async def close(self) -> None:
        """Close the underlying HTTP client if owned by this instance."""
        if self._owns_client and not self._client.is_closed:
            await self._client.aclose()

    async def __aenter__(self) -> "NaverSearchAdClient":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:  # noqa: ANN001
        await self.close()

    @staticmethod
    def _parse_keyword_item(raw: dict[str, Any]) -> KeywordStat:
        """Parse one ``keywordList`` entry into a ``KeywordStat``."""
        pc, pc_masked = parse_count(raw.get("monthlyPcQcCnt", 0))
        mobile, mobile_masked = parse_count(raw.get("monthlyMobileQcCnt", 0))

        def _num(key: str) -> float:
            try:
                return float(raw.get(key, 0) or 0)
            except (TypeError, ValueError):
                return 0.0

        return KeywordStat(
            keyword=str(raw.get("relKeyword", "")),
            monthly_pc=pc,
            monthly_mobile=mobile,
            monthly_ave_pc_clicks=_num("monthlyAvePcClkCnt"),
            monthly_ave_mobile_clicks=_num("monthlyAveMobileClkCnt"),
            monthly_ave_pc_ctr=_num("monthlyAvePcCtr"),
            monthly_ave_mobile_ctr=_num("monthlyAveMobileCtr"),
            pl_avg_depth=int(_num("plAvgDepth")),
            comp_idx=str(raw.get("compIdx", "")),
            is_masked=pc_masked or mobile_masked,
        )

    async def get_keyword_stats(
        self,
        hint_keywords: list[str],
        include_hint_keywords: bool = True,
    ) -> list[KeywordStat]:
        """
        Fetch related keywords and absolute monthly search volumes.

        Args:
            hint_keywords: Up to 5 seed keywords. More than 5 raises ``ValueError``.
            include_hint_keywords: Pass ``includeHintKeywords=1`` so the seed
                keywords themselves are returned alongside related ones.

        Returns:
            List of ``KeywordStat`` (related + optionally the seeds).

        Raises:
            ValueError: If more than ``MAX_HINT_KEYWORDS`` hints are supplied.
            RateLimitError: On HTTP 429 after all retries.
            APIError: On any other non-successful response.
        """
        if not hint_keywords:
            return []
        if len(hint_keywords) > MAX_HINT_KEYWORDS:
            raise ValueError(
                f"At most {MAX_HINT_KEYWORDS} hint keywords are allowed per call; "
                f"got {len(hint_keywords)}"
            )

        # Naver expects comma-separated hints with NO spaces around commas, and
        # the keywords themselves stripped of internal spaces.
        hint_param = ",".join(k.replace(" ", "") for k in hint_keywords)
        params = {
            "hintKeywords": hint_param,
            "showDetail": "1",
            "includeHintKeywords": "1" if include_hint_keywords else "0",
        }

        logger.info("searchad_keywordstool", hint_count=len(hint_keywords))
        data = await self._request("GET", KEYWORDSTOOL_PATH, params=params)

        raw_list = data.get("keywordList", []) or []
        return [self._parse_keyword_item(item) for item in raw_list]

    async def _request(
        self,
        method: str,
        uri: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute a signed, rate-limited request with retry/backoff."""
        url = f"{SEARCHAD_BASE_URL}{uri}"

        for attempt in range(MAX_RETRIES):
            # The keyword tool is throttled; pace requests before signing so the
            # timestamp in the signature stays fresh.
            await self._rate_limiter.acquire(timeout=30.0)
            headers = self._auth.get_auth_headers(method=method, uri=uri)

            try:
                response = await self._client.request(
                    method=method.upper(), url=url, headers=headers, params=params
                )
            except (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout) as exc:
                logger.warning("searchad_network_error", error=str(exc), attempt=attempt + 1)
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(INITIAL_BACKOFF * (BACKOFF_MULTIPLIER ** attempt))
                    continue
                raise APIError(
                    message=f"Naver Search Ad network error after {MAX_RETRIES} retries: {exc}",
                    api_name="naver_searchad",
                    original_error=exc,
                ) from exc

            if response.status_code == 429:
                retry_after = int(response.headers.get("Retry-After", "1"))
                logger.warning("searchad_rate_limit", retry_after=retry_after, attempt=attempt + 1)
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(retry_after)
                    continue
                raise RateLimitError(
                    message="Naver Search Ad API rate limit exceeded",
                    api_name="naver_searchad",
                    retry_after=retry_after,
                )

            if response.status_code >= 500 and attempt < MAX_RETRIES - 1:
                logger.warning("searchad_server_error", status_code=response.status_code)
                await asyncio.sleep(INITIAL_BACKOFF * (BACKOFF_MULTIPLIER ** attempt))
                continue

            if response.status_code >= 400:
                raise APIError(
                    message=f"Naver Search Ad API error: HTTP {response.status_code}",
                    api_name="naver_searchad",
                    status_code=response.status_code,
                    response_body=response.text,
                )

            return response.json()

        raise APIError(
            message=f"Naver Search Ad API failed after {MAX_RETRIES} retries",
            api_name="naver_searchad",
        )
