"""
중복 실행 방지 (Idempotency) 모듈

동일한 작업이 중복 실행되는 것을 방지합니다.

주요 기능:
    - SHA256 기반 멱등성 키 생성
      key = SHA256(job_type + entity_id + timestamp_truncated_to_hour)
    - DB(JobRun 모델) 기반 상태 추적
    - 비동기(async) 인터페이스

상태 흐름:
    (없음) -> running -> completed
                     \\-> failed
"""

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dropagent.db.models import JobRun
from dropagent.utils.exceptions import IdempotencyError
from dropagent.utils.logging import get_logger

logger = get_logger(__name__)


class IdempotencyManager:
    """
    멱등성 관리자

    SHA256 키를 생성하고 JobRun 테이블을 통해
    작업의 중복 실행을 방지합니다.
    """

    # ------------------------------------------------------------------
    # 키 생성
    # ------------------------------------------------------------------

    @staticmethod
    def generate_key(
        job_type: str,
        entity_id: str,
        timestamp: datetime | None = None,
    ) -> str:
        """
        멱등성 키를 생성합니다.

        SHA256(job_type + entity_id + timestamp_truncated_to_hour)
        timestamp를 시간 단위로 truncate 하여 동일 시간대 중복 호출을 방지합니다.

        Args:
            job_type: 작업 타입 (예: "product_analysis", "order_sync")
            entity_id: 엔티티 ID (예: 상품 ID, 주문 ID)
            timestamp: 기준 시각 (기본값: 현재 UTC 시각)

        Returns:
            str: SHA256 해시 (64자 hex)

        Examples:
            >>> IdempotencyManager.generate_key("product_analysis", "12345")
            'a1b2c3...'
        """
        ts = timestamp or datetime.now(UTC)
        # 시간 단위 truncate (분/초/마이크로초 제거)
        truncated = ts.replace(minute=0, second=0, microsecond=0)

        payload = json.dumps(
            {
                "job_type": job_type,
                "entity_id": str(entity_id),
                "hour": truncated.isoformat(),
            },
            sort_keys=True,
            ensure_ascii=False,
        )

        key = hashlib.sha256(payload.encode("utf-8")).hexdigest()

        logger.debug(
            "idempotency_key_generated",
            job_type=job_type,
            entity_id=entity_id,
            hour=truncated.isoformat(),
            key=key[:12] + "...",
        )
        return key

    # ------------------------------------------------------------------
    # 획득 / 완료 / 실패
    # ------------------------------------------------------------------

    @staticmethod
    async def check_and_acquire(
        session: AsyncSession,
        idempotency_key: str,
        job_type: str = "",
    ) -> bool:
        """
        작업 실행 가능 여부를 확인하고 획득합니다.

        이미 running 또는 completed 상태인 레코드가 있으면 False 를 반환합니다.
        레코드가 없으면 running 상태로 새 레코드를 생성합니다.

        Args:
            session: SQLAlchemy AsyncSession
            idempotency_key: 멱등성 키 (SHA256 해시)
            job_type: 작업 타입 (새 레코드 생성 시 기록)

        Returns:
            bool: True이면 획득 성공(실행 가능), False이면 이미 존재

        Examples:
            >>> acquired = await manager.check_and_acquire(session, key)
            >>> if acquired:
            ...     # 작업 실행
            ...     await manager.mark_completed(session, key, {"ok": True})
        """
        stmt = select(JobRun).where(JobRun.idempotency_key == idempotency_key)
        result = await session.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing is not None:
            if existing.status in ("running", "completed"):
                logger.info(
                    "idempotency_already_exists",
                    key=idempotency_key[:12] + "...",
                    status=existing.status,
                )
                return False
            # failed 상태인 경우 재시도 허용: running 으로 업데이트
            existing.status = "running"
            existing.retry_count += 1
            existing.error_message = None
            existing.started_at = datetime.now(UTC)
            await session.flush()
            logger.info(
                "idempotency_retry_acquired",
                key=idempotency_key[:12] + "...",
                retry_count=existing.retry_count,
            )
            return True

        # 새 레코드 생성
        now = datetime.now(UTC)
        new_run = JobRun(
            idempotency_key=idempotency_key,
            job_type=job_type,
            status="running",
            retry_count=0,
            started_at=now,
        )
        session.add(new_run)
        await session.flush()

        logger.info(
            "idempotency_acquired",
            key=idempotency_key[:12] + "...",
            job_type=job_type,
        )
        return True

    @staticmethod
    async def mark_completed(
        session: AsyncSession,
        idempotency_key: str,
        result: dict[str, Any] | None = None,
    ) -> None:
        """
        작업을 완료 상태로 표시합니다.

        Args:
            session: SQLAlchemy AsyncSession
            idempotency_key: 멱등성 키
            result: 작업 결과 (JSONB로 저장)

        Raises:
            IdempotencyError: 해당 키의 레코드가 없는 경우
        """
        stmt = select(JobRun).where(JobRun.idempotency_key == idempotency_key)
        res = await session.execute(stmt)
        record = res.scalar_one_or_none()

        if record is None:
            raise IdempotencyError(
                message=f"완료 처리할 레코드를 찾을 수 없습니다: {idempotency_key[:12]}...",
                operation_id=idempotency_key,
            )

        record.status = "completed"
        record.output_result = result
        record.completed_at = datetime.now(UTC)
        await session.flush()

        logger.info(
            "idempotency_completed",
            key=idempotency_key[:12] + "...",
        )

    @staticmethod
    async def mark_failed(
        session: AsyncSession,
        idempotency_key: str,
        error: str,
    ) -> None:
        """
        작업을 실패 상태로 표시합니다.

        Args:
            session: SQLAlchemy AsyncSession
            idempotency_key: 멱등성 키
            error: 에러 메시지

        Raises:
            IdempotencyError: 해당 키의 레코드가 없는 경우
        """
        stmt = select(JobRun).where(JobRun.idempotency_key == idempotency_key)
        res = await session.execute(stmt)
        record = res.scalar_one_or_none()

        if record is None:
            raise IdempotencyError(
                message=f"실패 처리할 레코드를 찾을 수 없습니다: {idempotency_key[:12]}...",
                operation_id=idempotency_key,
            )

        record.status = "failed"
        record.error_message = error
        await session.flush()

        logger.warning(
            "idempotency_failed",
            key=idempotency_key[:12] + "...",
            error=error[:200],
        )

    # ------------------------------------------------------------------
    # 조회 헬퍼
    # ------------------------------------------------------------------

    @staticmethod
    async def get_status(
        session: AsyncSession,
        idempotency_key: str,
    ) -> str | None:
        """
        작업 상태를 조회합니다.

        Args:
            session: SQLAlchemy AsyncSession
            idempotency_key: 멱등성 키

        Returns:
            Optional[str]: "running", "completed", "failed" 중 하나. 없으면 None
        """
        stmt = select(JobRun.status).where(
            JobRun.idempotency_key == idempotency_key
        )
        res = await session.execute(stmt)
        row = res.scalar_one_or_none()
        return row
