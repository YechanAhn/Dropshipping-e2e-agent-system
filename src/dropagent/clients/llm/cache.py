"""
LLM 응답 캐시 모듈

SHA256 기반 키를 사용하는 인메모리 LRU 캐시입니다.
TTL(Time-To-Live) 만료와 최대 크기 제한을 지원하며,
스레드 안전하게 동작합니다.
"""

import hashlib
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass

from dropagent.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class _CacheEntry:
    """캐시 엔트리 (값 + 만료 시각)."""

    value: str
    expires_at: float


@dataclass
class _CacheStats:
    """캐시 적중/미적중 통계."""

    hits: int = 0
    misses: int = 0
    evictions: int = 0
    expirations: int = 0

    @property
    def total_requests(self) -> int:
        return self.hits + self.misses

    @property
    def hit_rate(self) -> float:
        if self.total_requests == 0:
            return 0.0
        return self.hits / self.total_requests


class LLMCache:
    """
    TTL 기반 인메모리 LLM 응답 캐시.

    OrderedDict를 사용하여 LRU 방식으로 가장 오래된 항목부터 제거합니다.
    모든 공개 메서드는 threading.Lock으로 보호됩니다.

    Args:
        max_size: 캐시에 보관할 최대 항목 수. 초과 시 LRU 제거.
        ttl_seconds: 각 항목의 생존 시간(초). 0이면 만료 없음.

    Examples:
        >>> cache = LLMCache(max_size=100, ttl_seconds=600)
        >>> cache.set("claude-sonnet-4-20250514", "Translate this", "번역 결과")
        >>> cache.get("claude-sonnet-4-20250514", "Translate this")
        '번역 결과'
    """

    def __init__(self, max_size: int = 1000, ttl_seconds: int = 3600) -> None:
        self._max_size = max(1, max_size)
        self._ttl_seconds = max(0, ttl_seconds)
        self._cache: OrderedDict[str, _CacheEntry] = OrderedDict()
        self._lock = threading.Lock()
        self._stats = _CacheStats()

        logger.info(
            "llm_cache_initialized",
            max_size=self._max_size,
            ttl_seconds=self._ttl_seconds,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _make_key(model: str, prompt: str) -> str:
        """
        모델 이름과 프롬프트로부터 SHA256 해시 키를 생성합니다.

        Args:
            model: Claude 모델 식별자.
            prompt: 전체 프롬프트 문자열.

        Returns:
            64자 hex 다이제스트.
        """
        raw = f"{model}::{prompt}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _is_expired(self, entry: _CacheEntry) -> bool:
        """TTL이 0이 아닌 경우 만료 여부를 확인합니다."""
        if self._ttl_seconds == 0:
            return False
        return time.monotonic() > entry.expires_at

    def _evict_oldest(self) -> None:
        """캐시가 max_size를 초과하면 가장 오래된 항목을 제거합니다.

        호출자가 _lock을 보유한 상태에서만 호출해야 합니다.
        """
        while len(self._cache) > self._max_size:
            evicted_key, _ = self._cache.popitem(last=False)
            self._stats.evictions += 1
            logger.debug("llm_cache_evicted", key=evicted_key[:12])

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self, model: str, prompt: str) -> str | None:
        """
        캐시에서 응답을 조회합니다.

        TTL이 만료되었으면 해당 항목을 삭제하고 None을 반환합니다.

        Args:
            model: Claude 모델 식별자.
            prompt: 전체 프롬프트 문자열.

        Returns:
            캐시된 응답 문자열, 또는 캐시 미스/만료 시 None.
        """
        key = self._make_key(model, prompt)

        with self._lock:
            entry = self._cache.get(key)

            if entry is None:
                self._stats.misses += 1
                return None

            if self._is_expired(entry):
                del self._cache[key]
                self._stats.expirations += 1
                self._stats.misses += 1
                logger.debug("llm_cache_expired", key=key[:12])
                return None

            # Move to end for LRU ordering
            self._cache.move_to_end(key)
            self._stats.hits += 1
            logger.debug("llm_cache_hit", key=key[:12])
            return entry.value

    def set(self, model: str, prompt: str, response: str) -> None:
        """
        응답을 캐시에 저장합니다.

        이미 존재하는 키는 갱신하며, max_size 초과 시 가장 오래된 항목을 제거합니다.

        Args:
            model: Claude 모델 식별자.
            prompt: 전체 프롬프트 문자열.
            response: 캐시할 LLM 응답.
        """
        key = self._make_key(model, prompt)
        expires_at = time.monotonic() + self._ttl_seconds if self._ttl_seconds > 0 else float("inf")

        with self._lock:
            # If the key already exists, update and move to end
            if key in self._cache:
                self._cache[key] = _CacheEntry(value=response, expires_at=expires_at)
                self._cache.move_to_end(key)
            else:
                self._cache[key] = _CacheEntry(value=response, expires_at=expires_at)

            self._evict_oldest()

        logger.debug("llm_cache_set", key=key[:12], model=model)

    def clear(self) -> None:
        """모든 캐시 항목과 통계를 초기화합니다."""
        with self._lock:
            count = len(self._cache)
            self._cache.clear()
            self._stats = _CacheStats()

        logger.info("llm_cache_cleared", cleared_items=count)

    @property
    def size(self) -> int:
        """현재 캐시에 저장된 항목 수."""
        with self._lock:
            return len(self._cache)

    @property
    def stats(self) -> dict:
        """
        캐시 적중/미적중 통계를 딕셔너리로 반환합니다.

        Returns:
            dict with keys: hits, misses, evictions, expirations,
                            total_requests, hit_rate, current_size, max_size.
        """
        with self._lock:
            return {
                "hits": self._stats.hits,
                "misses": self._stats.misses,
                "evictions": self._stats.evictions,
                "expirations": self._stats.expirations,
                "total_requests": self._stats.total_requests,
                "hit_rate": round(self._stats.hit_rate, 4),
                "current_size": len(self._cache),
                "max_size": self._max_size,
            }
