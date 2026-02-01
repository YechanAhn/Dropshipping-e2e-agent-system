"""
Tests for IdempotencyManager.

Covers:
    - Key generation consistency (same inputs = same key)
    - Key generation uniqueness (different inputs = different keys)
    - Key generation with hour truncation
    - Mock DB session for check_and_acquire tests
    - mark_completed and mark_failed
"""

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from dropagent.core.idempotency import IdempotencyManager
from dropagent.utils.exceptions import IdempotencyError

# =====================================================================
# Key generation consistency
# =====================================================================

class TestKeyGenerationConsistency:
    """Tests for IdempotencyManager.generate_key() consistency."""

    def test_same_inputs_same_key(self):
        """Same inputs produce the same key."""
        ts = datetime(2025, 1, 15, 10, 30, 45, tzinfo=UTC)
        key1 = IdempotencyManager.generate_key("product_analysis", "12345", ts)
        key2 = IdempotencyManager.generate_key("product_analysis", "12345", ts)
        assert key1 == key2

    def test_key_is_sha256_hex(self):
        """Key is a 64-character hex string (SHA256)."""
        key = IdempotencyManager.generate_key("job_type", "entity_1")
        assert len(key) == 64
        assert all(c in "0123456789abcdef" for c in key)

    def test_deterministic_across_calls(self):
        """Multiple calls with identical timestamp produce identical keys."""
        ts = datetime(2025, 6, 1, 14, 0, 0, tzinfo=UTC)
        keys = [
            IdempotencyManager.generate_key("order_sync", "ORD-999", ts)
            for _ in range(10)
        ]
        assert len(set(keys)) == 1


# =====================================================================
# Key generation uniqueness
# =====================================================================

class TestKeyGenerationUniqueness:
    """Tests for IdempotencyManager.generate_key() uniqueness."""

    def test_different_job_type_different_key(self):
        """Different job_type produces different key."""
        ts = datetime(2025, 1, 15, 10, 0, 0, tzinfo=UTC)
        key1 = IdempotencyManager.generate_key("product_analysis", "12345", ts)
        key2 = IdempotencyManager.generate_key("order_sync", "12345", ts)
        assert key1 != key2

    def test_different_entity_id_different_key(self):
        """Different entity_id produces different key."""
        ts = datetime(2025, 1, 15, 10, 0, 0, tzinfo=UTC)
        key1 = IdempotencyManager.generate_key("product_analysis", "12345", ts)
        key2 = IdempotencyManager.generate_key("product_analysis", "67890", ts)
        assert key1 != key2

    def test_different_hour_different_key(self):
        """Different hours produce different keys."""
        ts1 = datetime(2025, 1, 15, 10, 0, 0, tzinfo=UTC)
        ts2 = datetime(2025, 1, 15, 11, 0, 0, tzinfo=UTC)
        key1 = IdempotencyManager.generate_key("product_analysis", "12345", ts1)
        key2 = IdempotencyManager.generate_key("product_analysis", "12345", ts2)
        assert key1 != key2


# =====================================================================
# Hour truncation
# =====================================================================

class TestKeyHourTruncation:
    """Tests for hour truncation in key generation."""

    def test_same_hour_different_minutes_same_key(self):
        """Different minutes within the same hour produce the same key."""
        ts1 = datetime(2025, 1, 15, 10, 0, 0, tzinfo=UTC)
        ts2 = datetime(2025, 1, 15, 10, 30, 45, tzinfo=UTC)
        ts3 = datetime(2025, 1, 15, 10, 59, 59, tzinfo=UTC)
        key1 = IdempotencyManager.generate_key("job", "ent", ts1)
        key2 = IdempotencyManager.generate_key("job", "ent", ts2)
        key3 = IdempotencyManager.generate_key("job", "ent", ts3)
        assert key1 == key2 == key3

    def test_different_seconds_same_hour_same_key(self):
        """Different seconds within the same minute produce the same key."""
        ts1 = datetime(2025, 1, 15, 10, 15, 0, tzinfo=UTC)
        ts2 = datetime(2025, 1, 15, 10, 15, 59, tzinfo=UTC)
        key1 = IdempotencyManager.generate_key("job", "ent", ts1)
        key2 = IdempotencyManager.generate_key("job", "ent", ts2)
        assert key1 == key2

    def test_microseconds_truncated(self):
        """Microseconds are truncated."""
        ts1 = datetime(2025, 1, 15, 10, 0, 0, 0, tzinfo=UTC)
        ts2 = datetime(2025, 1, 15, 10, 0, 0, 999999, tzinfo=UTC)
        key1 = IdempotencyManager.generate_key("job", "ent", ts1)
        key2 = IdempotencyManager.generate_key("job", "ent", ts2)
        assert key1 == key2

    def test_default_timestamp_is_utc_now(self):
        """Without timestamp, uses current UTC time (key is generated without error)."""
        key = IdempotencyManager.generate_key("job", "ent")
        assert isinstance(key, str)
        assert len(key) == 64


# =====================================================================
# check_and_acquire (mocked DB)
# =====================================================================

class TestCheckAndAcquire:
    """Tests for IdempotencyManager.check_and_acquire() with mocked DB."""

    async def test_acquire_new_record(self, mock_async_session):
        """Acquiring a new key creates a running record and returns True."""
        # No existing record (default mock behavior)
        result = await IdempotencyManager.check_and_acquire(
            mock_async_session, "test_key_abc123", "product_analysis"
        )
        assert result is True
        mock_async_session.add.assert_called_once()
        mock_async_session.flush.assert_awaited()

    async def test_acquire_existing_running_returns_false(self, mock_async_session):
        """Existing record in 'running' status returns False."""
        existing_record = MagicMock()
        existing_record.status = "running"
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_record
        mock_async_session.execute.return_value = mock_result

        result = await IdempotencyManager.check_and_acquire(
            mock_async_session, "test_key_abc123"
        )
        assert result is False

    async def test_acquire_existing_completed_returns_false(self, mock_async_session):
        """Existing record in 'completed' status returns False."""
        existing_record = MagicMock()
        existing_record.status = "completed"
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_record
        mock_async_session.execute.return_value = mock_result

        result = await IdempotencyManager.check_and_acquire(
            mock_async_session, "test_key_abc123"
        )
        assert result is False

    async def test_acquire_existing_failed_allows_retry(self, mock_async_session):
        """Existing record in 'failed' status allows retry and returns True."""
        existing_record = MagicMock()
        existing_record.status = "failed"
        existing_record.retry_count = 1
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_record
        mock_async_session.execute.return_value = mock_result

        result = await IdempotencyManager.check_and_acquire(
            mock_async_session, "test_key_abc123"
        )
        assert result is True
        assert existing_record.status == "running"
        assert existing_record.retry_count == 2
        assert existing_record.error_message is None
        mock_async_session.flush.assert_awaited()


# =====================================================================
# mark_completed
# =====================================================================

class TestMarkCompleted:
    """Tests for IdempotencyManager.mark_completed()."""

    async def test_mark_completed_success(self, mock_async_session):
        """Marking a completed record sets status and output."""
        existing_record = MagicMock()
        existing_record.status = "running"
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_record
        mock_async_session.execute.return_value = mock_result

        await IdempotencyManager.mark_completed(
            mock_async_session,
            "test_key_abc123",
            result={"items_processed": 5},
        )
        assert existing_record.status == "completed"
        assert existing_record.output_result == {"items_processed": 5}
        mock_async_session.flush.assert_awaited()

    async def test_mark_completed_no_record_raises(self, mock_async_session):
        """Marking completed with no existing record raises IdempotencyError."""
        # Default mock returns None for scalar_one_or_none
        with pytest.raises(IdempotencyError):
            await IdempotencyManager.mark_completed(
                mock_async_session,
                "nonexistent_key",
            )

    async def test_mark_completed_with_none_result(self, mock_async_session):
        """Marking completed with None result sets output_result to None."""
        existing_record = MagicMock()
        existing_record.status = "running"
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_record
        mock_async_session.execute.return_value = mock_result

        await IdempotencyManager.mark_completed(
            mock_async_session,
            "test_key_abc123",
            result=None,
        )
        assert existing_record.status == "completed"
        assert existing_record.output_result is None


# =====================================================================
# mark_failed
# =====================================================================

class TestMarkFailed:
    """Tests for IdempotencyManager.mark_failed()."""

    async def test_mark_failed_success(self, mock_async_session):
        """Marking a failed record sets status and error message."""
        existing_record = MagicMock()
        existing_record.status = "running"
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_record
        mock_async_session.execute.return_value = mock_result

        await IdempotencyManager.mark_failed(
            mock_async_session,
            "test_key_abc123",
            error="Connection timeout",
        )
        assert existing_record.status == "failed"
        assert existing_record.error_message == "Connection timeout"
        mock_async_session.flush.assert_awaited()

    async def test_mark_failed_no_record_raises(self, mock_async_session):
        """Marking failed with no existing record raises IdempotencyError."""
        with pytest.raises(IdempotencyError):
            await IdempotencyManager.mark_failed(
                mock_async_session,
                "nonexistent_key",
                error="some error",
            )


# =====================================================================
# get_status
# =====================================================================

class TestGetStatus:
    """Tests for IdempotencyManager.get_status()."""

    async def test_get_status_returns_status(self, mock_async_session):
        """get_status returns the status string when record exists."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = "completed"
        mock_async_session.execute.return_value = mock_result

        status = await IdempotencyManager.get_status(
            mock_async_session, "test_key"
        )
        assert status == "completed"

    async def test_get_status_returns_none_when_not_found(self, mock_async_session):
        """get_status returns None when record doesn't exist."""
        status = await IdempotencyManager.get_status(
            mock_async_session, "nonexistent_key"
        )
        assert status is None
