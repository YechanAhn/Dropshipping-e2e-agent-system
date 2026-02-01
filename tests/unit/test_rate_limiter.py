"""
Tests for TokenBucketRateLimiter.

Covers:
    - Token acquisition
    - Rate limiting (should wait)
    - acquire_or_fail when no tokens available
    - Factory functions
"""

import asyncio
import time

import pytest

from dropagent.core.rate_limiter import (
    TokenBucketRateLimiter,
    create_naver_commerce_limiter,
    create_naver_search_limiter,
)
from dropagent.utils.exceptions import RateLimitError

# =====================================================================
# Construction / validation
# =====================================================================

class TestConstruction:
    """Tests for TokenBucketRateLimiter construction."""

    def test_valid_construction(self):
        """Valid parameters create a limiter."""
        limiter = TokenBucketRateLimiter(rate=5.0, capacity=10, name="test")
        assert limiter.rate == 5.0
        assert limiter.capacity == 10
        assert limiter.name == "test"

    def test_invalid_rate_raises(self):
        """Zero or negative rate raises ValueError."""
        with pytest.raises(ValueError, match="rate"):
            TokenBucketRateLimiter(rate=0, capacity=5)
        with pytest.raises(ValueError, match="rate"):
            TokenBucketRateLimiter(rate=-1.0, capacity=5)

    def test_invalid_capacity_raises(self):
        """Zero or negative capacity raises ValueError."""
        with pytest.raises(ValueError, match="capacity"):
            TokenBucketRateLimiter(rate=1.0, capacity=0)
        with pytest.raises(ValueError, match="capacity"):
            TokenBucketRateLimiter(rate=1.0, capacity=-5)

    def test_default_name(self):
        """Default name is generated from rate."""
        limiter = TokenBucketRateLimiter(rate=2.0, capacity=5)
        assert "2.0" in limiter.name


# =====================================================================
# Token acquisition
# =====================================================================

class TestTokenAcquisition:
    """Tests for basic token acquisition."""

    async def test_acquire_when_tokens_available(self):
        """acquire() returns immediately when tokens are available."""
        limiter = TokenBucketRateLimiter(rate=10.0, capacity=5)
        start = time.monotonic()
        await limiter.acquire()
        elapsed = time.monotonic() - start
        assert elapsed < 0.1  # Should be nearly instant

    async def test_acquire_consumes_token(self):
        """Each acquire() consumes one token."""
        limiter = TokenBucketRateLimiter(rate=100.0, capacity=3)
        tokens_before = await limiter.tokens_available()
        assert tokens_before == pytest.approx(3.0, abs=0.5)

        await limiter.acquire()
        tokens_after = await limiter.tokens_available()
        # Should be approximately 2 (with possible refill)
        assert tokens_after < tokens_before

    async def test_acquire_multiple_within_capacity(self):
        """Multiple acquires within capacity succeed immediately."""
        limiter = TokenBucketRateLimiter(rate=10.0, capacity=5)
        start = time.monotonic()
        for _ in range(5):
            await limiter.acquire()
        elapsed = time.monotonic() - start
        # All 5 should complete very fast (from initial capacity)
        assert elapsed < 0.5

    async def test_tokens_available_reflects_refill(self):
        """tokens_available reflects refilled tokens."""
        limiter = TokenBucketRateLimiter(rate=1000.0, capacity=10)
        # Drain all tokens
        for _ in range(10):
            await limiter.acquire()
        # Wait a tiny bit for refill
        await asyncio.sleep(0.02)
        tokens = await limiter.tokens_available()
        assert tokens > 0

    async def test_reset_restores_capacity(self):
        """reset() restores tokens to full capacity."""
        limiter = TokenBucketRateLimiter(rate=1.0, capacity=5)
        for _ in range(5):
            await limiter.acquire()
        await limiter.reset()
        tokens = await limiter.tokens_available()
        assert tokens == pytest.approx(5.0, abs=0.1)


# =====================================================================
# Rate limiting behavior
# =====================================================================

class TestRateLimiting:
    """Tests for rate limiting behavior."""

    async def test_acquire_waits_when_exhausted(self):
        """acquire() waits when tokens are exhausted."""
        # Very slow refill rate so we can measure the wait
        limiter = TokenBucketRateLimiter(rate=10.0, capacity=1)
        await limiter.acquire()  # consume the only token

        start = time.monotonic()
        await limiter.acquire()  # must wait for refill
        elapsed = time.monotonic() - start
        # At 10 tokens/sec, should take ~0.1 seconds to get a new token
        assert elapsed >= 0.05

    async def test_acquire_with_timeout_succeeds(self):
        """acquire() with sufficient timeout succeeds."""
        limiter = TokenBucketRateLimiter(rate=10.0, capacity=1)
        await limiter.acquire()  # consume token

        # Timeout of 1 second should be enough for rate=10/s
        await limiter.acquire(timeout=1.0)

    async def test_acquire_with_timeout_fails(self):
        """acquire() with insufficient timeout raises RateLimitError."""
        # Very slow rate: 0.5 tokens/sec -> 2 seconds per token
        limiter = TokenBucketRateLimiter(rate=0.5, capacity=1)
        await limiter.acquire()  # consume token

        with pytest.raises(RateLimitError):
            # Timeout too short to wait for next token
            await limiter.acquire(timeout=0.01)


# =====================================================================
# acquire_or_fail
# =====================================================================

class TestAcquireOrFail:
    """Tests for acquire_or_fail()."""

    async def test_acquire_or_fail_with_tokens(self):
        """acquire_or_fail succeeds when tokens are available."""
        limiter = TokenBucketRateLimiter(rate=10.0, capacity=5)
        await limiter.acquire_or_fail()  # Should not raise

    async def test_acquire_or_fail_no_tokens_raises(self):
        """acquire_or_fail raises RateLimitError when no tokens."""
        limiter = TokenBucketRateLimiter(rate=0.1, capacity=1)
        await limiter.acquire()  # consume the only token

        with pytest.raises(RateLimitError):
            await limiter.acquire_or_fail()

    async def test_acquire_or_fail_is_immediate(self):
        """acquire_or_fail returns or raises immediately (no waiting)."""
        limiter = TokenBucketRateLimiter(rate=0.1, capacity=1)
        await limiter.acquire()  # consume token

        start = time.monotonic()
        with pytest.raises(RateLimitError):
            await limiter.acquire_or_fail()
        elapsed = time.monotonic() - start
        assert elapsed < 0.1  # Should fail nearly instantly


# =====================================================================
# Factory functions
# =====================================================================

class TestFactoryFunctions:
    """Tests for convenience factory functions."""

    def test_naver_commerce_limiter(self):
        """create_naver_commerce_limiter creates correct limiter."""
        limiter = create_naver_commerce_limiter()
        assert limiter.rate == 2.0
        assert limiter.capacity == 5
        assert limiter.name == "naver_commerce_api"

    def test_naver_search_limiter(self):
        """create_naver_search_limiter creates correct limiter."""
        limiter = create_naver_search_limiter()
        assert limiter.rate == 10.0
        assert limiter.capacity == 20
        assert limiter.name == "naver_search_api"

    async def test_commerce_limiter_functional(self):
        """Commerce limiter can acquire tokens."""
        limiter = create_naver_commerce_limiter()
        await limiter.acquire()
        tokens = await limiter.tokens_available()
        assert tokens >= 0

    async def test_search_limiter_functional(self):
        """Search limiter can acquire tokens."""
        limiter = create_naver_search_limiter()
        await limiter.acquire()
        tokens = await limiter.tokens_available()
        assert tokens >= 0


# =====================================================================
# Properties and edge cases
# =====================================================================

class TestPropertiesAndEdgeCases:
    """Tests for properties and edge cases."""

    def test_properties_readonly(self):
        """rate, capacity, name properties return correct values."""
        limiter = TokenBucketRateLimiter(rate=3.0, capacity=7, name="my_limiter")
        assert limiter.rate == 3.0
        assert limiter.capacity == 7
        assert limiter.name == "my_limiter"

    async def test_concurrent_acquires(self):
        """Multiple concurrent acquire calls are safe."""
        limiter = TokenBucketRateLimiter(rate=100.0, capacity=10)
        tasks = [limiter.acquire() for _ in range(10)]
        await asyncio.gather(*tasks)
        # All 10 should complete without error

    async def test_high_rate_limiter(self):
        """High-rate limiter handles many requests quickly."""
        limiter = TokenBucketRateLimiter(rate=1000.0, capacity=100)
        start = time.monotonic()
        for _ in range(50):
            await limiter.acquire()
        elapsed = time.monotonic() - start
        assert elapsed < 1.0  # Should be very fast
