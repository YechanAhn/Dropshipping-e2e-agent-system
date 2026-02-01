"""
Token Bucket 레이트 리미터

asyncio 기반 Token Bucket 알고리즘으로 API 호출 빈도를 제한합니다.

주요 사용처:
    - 네이버 커머스 API: 초당 2회, 버스트 5
    - 네이버 검색 API: 초당 10회, 버스트 20

특징:
    - Redis 없이 인-프로세스로 동작
    - asyncio.Lock 으로 동시성 안전
    - acquire()  : 토큰이 확보될 때까지 대기
    - acquire_or_fail() : 즉시 시도, 실패 시 RateLimitError 발생
"""

import asyncio
import time

from dropagent.utils.exceptions import RateLimitError
from dropagent.utils.logging import get_logger

logger = get_logger(__name__)


class TokenBucketRateLimiter:
    """
    Token Bucket 레이트 리미터 (asyncio)

    초당 rate 개의 토큰이 리필되며, 최대 capacity 개까지 축적됩니다.
    acquire() 호출 시 토큰 1개를 소비하고, 토큰이 없으면 대기합니다.
    """

    def __init__(
        self,
        rate: float,
        capacity: int,
        name: str | None = None,
    ) -> None:
        """
        Args:
            rate: 초당 토큰 리필 속도 (예: 2.0 = 초당 2개)
            capacity: 최대 토큰 수 (버스트 허용량)
            name: 리미터 식별 이름 (로그용)

        Raises:
            ValueError: rate 또는 capacity가 유효하지 않은 경우
        """
        if rate <= 0:
            raise ValueError(f"rate는 양수여야 합니다. 입력값: {rate}")
        if capacity <= 0:
            raise ValueError(f"capacity는 양수여야 합니다. 입력값: {capacity}")

        self._rate: float = rate
        self._capacity: int = capacity
        self._name: str = name or f"rate_limiter_{rate}/s"

        # 현재 토큰 수 (float 으로 관리하여 정밀 리필)
        self._tokens: float = float(capacity)
        self._last_refill: float = time.monotonic()
        self._lock: asyncio.Lock = asyncio.Lock()

        logger.info(
            "token_bucket_initialized",
            name=self._name,
            rate=self._rate,
            capacity=self._capacity,
        )

    # ------------------------------------------------------------------
    # 속성
    # ------------------------------------------------------------------

    @property
    def rate(self) -> float:
        """초당 토큰 리필 속도"""
        return self._rate

    @property
    def capacity(self) -> int:
        """최대 토큰 수"""
        return self._capacity

    @property
    def name(self) -> str:
        """리미터 이름"""
        return self._name

    # ------------------------------------------------------------------
    # 내부 로직
    # ------------------------------------------------------------------

    def _refill(self) -> None:
        """
        경과 시간에 비례하여 토큰을 리필합니다.

        Lock 내부에서만 호출되어야 합니다.
        """
        now = time.monotonic()
        elapsed = now - self._last_refill
        tokens_to_add = elapsed * self._rate
        self._tokens = min(float(self._capacity), self._tokens + tokens_to_add)
        self._last_refill = now

    def _try_consume(self) -> bool:
        """
        토큰 1개 소비를 시도합니다.

        Lock 내부에서만 호출되어야 합니다.

        Returns:
            bool: 소비 성공 여부
        """
        self._refill()
        if self._tokens >= 1.0:
            self._tokens -= 1.0
            return True
        return False

    def _wait_time_for_token(self) -> float:
        """
        다음 토큰이 사용 가능해질 때까지의 예상 대기 시간(초)을 반환합니다.

        Lock 내부에서만 호출되어야 합니다.

        Returns:
            float: 대기 시간 (초)
        """
        if self._tokens >= 1.0:
            return 0.0
        deficit = 1.0 - self._tokens
        return deficit / self._rate

    # ------------------------------------------------------------------
    # 공개 API
    # ------------------------------------------------------------------

    async def acquire(self, timeout: float | None = None) -> None:
        """
        토큰 1개가 확보될 때까지 비동기 대기합니다.

        토큰이 즉시 사용 가능하면 바로 반환하고,
        그렇지 않으면 리필될 때까지 sleep 합니다.

        Args:
            timeout: 최대 대기 시간(초). None이면 무제한 대기.

        Raises:
            RateLimitError: timeout 이내에 토큰을 확보하지 못한 경우
        """
        deadline = (time.monotonic() + timeout) if timeout is not None else None

        while True:
            async with self._lock:
                if self._try_consume():
                    return
                wait_time = self._wait_time_for_token()

            # deadline 검사
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RateLimitError(
                        message=(
                            f"[{self._name}] {timeout:.2f}초 내에 토큰을 확보하지 못했습니다."
                        ),
                        api_name=self._name,
                    )
                wait_time = min(wait_time, remaining)

            await asyncio.sleep(wait_time)

    async def acquire_or_fail(self) -> None:
        """
        토큰 1개를 즉시 소비합니다. 사용 가능한 토큰이 없으면 즉시 실패합니다.

        Raises:
            RateLimitError: 사용 가능한 토큰이 없는 경우
        """
        async with self._lock:
            if self._try_consume():
                return

        raise RateLimitError(
            message=f"[{self._name}] 사용 가능한 토큰이 없습니다.",
            api_name=self._name,
        )

    async def tokens_available(self) -> float:
        """
        현재 사용 가능한 토큰 수를 반환합니다.

        Returns:
            float: 현재 토큰 수 (리필 반영)
        """
        async with self._lock:
            self._refill()
            return self._tokens

    async def reset(self) -> None:
        """토큰을 최대 용량으로 초기화합니다."""
        async with self._lock:
            self._tokens = float(self._capacity)
            self._last_refill = time.monotonic()
        logger.info("rate_limiter_reset", name=self._name)


# =====================================================================
# 편의 팩토리 함수
# =====================================================================


def create_naver_commerce_limiter() -> TokenBucketRateLimiter:
    """
    네이버 커머스 API용 레이트 리미터를 생성합니다.

    사양: 초당 2회, 최대 버스트 5

    Returns:
        TokenBucketRateLimiter: 네이버 커머스 API 전용 리미터
    """
    return TokenBucketRateLimiter(
        rate=2.0,
        capacity=5,
        name="naver_commerce_api",
    )


def create_naver_search_limiter() -> TokenBucketRateLimiter:
    """
    네이버 검색 API용 레이트 리미터를 생성합니다.

    사양: 초당 10회, 최대 버스트 20

    Returns:
        TokenBucketRateLimiter: 네이버 검색 API 전용 리미터
    """
    return TokenBucketRateLimiter(
        rate=10.0,
        capacity=20,
        name="naver_search_api",
    )
