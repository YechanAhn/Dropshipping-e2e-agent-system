"""
Audit Log Repository - Database operations for the AuditLog model.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from dropagent.db.models import AuditLog
from dropagent.utils.exceptions import DatabaseError
from dropagent.utils.logging import get_logger

logger = get_logger(__name__)


class AuditLogRepository:
    """Repository for audit log recording and querying."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def log(
        self,
        action: str,
        entity_type: str,
        entity_id: str,
        before: dict | None = None,
        after: dict | None = None,
        actor: str = "system",
    ) -> AuditLog:
        """
        Create a new audit log entry.

        The before/after snapshots are stored in the model's `changes` JSONB column
        as ``{"before": ..., "after": ...}``.

        Args:
            action: Description of the action performed (e.g. 'product_created').
            entity_type: The type of entity affected (e.g. 'product', 'order').
            entity_id: The identifier of the affected entity.
            before: Optional snapshot of the entity state before the change.
            after: Optional snapshot of the entity state after the change.
            actor: Who performed the action (default: 'system').

        Returns:
            The newly created AuditLog instance.
        """
        try:
            changes = {}
            if before is not None:
                changes["before"] = before
            if after is not None:
                changes["after"] = after

            entry = AuditLog(
                actor=actor,
                action=action,
                entity_type=entity_type,
                entity_id=str(entity_id),
                changes=changes if changes else None,
            )
            self.session.add(entry)
            await self.session.flush()
            await self.session.refresh(entry)
            logger.info(
                "audit_log_created",
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                actor=actor,
            )
            return entry
        except Exception as e:
            await self.session.rollback()
            logger.error(
                "audit_log_create_error",
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                error=str(e),
            )
            raise DatabaseError(
                message="Failed to create audit log entry",
                operation="log",
                table="audit_logs",
                details={
                    "action": action,
                    "entity_type": entity_type,
                    "entity_id": entity_id,
                },
                original_error=e,
            ) from e

    async def get_by_entity(
        self,
        entity_type: str,
        entity_id: str,
        limit: int = 50,
    ) -> list[AuditLog]:
        """
        Get audit log entries for a specific entity.

        Args:
            entity_type: The type of entity (e.g. 'product').
            entity_id: The entity's identifier.
            limit: Maximum number of entries to return.

        Returns:
            List of AuditLog instances ordered by created_at descending.
        """
        try:
            stmt = (
                select(AuditLog)
                .where(AuditLog.entity_type == entity_type)
                .where(AuditLog.entity_id == str(entity_id))
                .order_by(AuditLog.created_at.desc())
                .limit(limit)
            )
            result = await self.session.execute(stmt)
            return list(result.scalars().all())
        except Exception as e:
            logger.error(
                "audit_log_get_by_entity_error",
                entity_type=entity_type,
                entity_id=entity_id,
                error=str(e),
            )
            raise DatabaseError(
                message="Failed to get audit logs by entity",
                operation="get_by_entity",
                table="audit_logs",
                details={"entity_type": entity_type, "entity_id": entity_id},
                original_error=e,
            ) from e

    async def get_by_action(self, action: str, limit: int = 100) -> list[AuditLog]:
        """
        Get audit log entries filtered by action.

        Args:
            action: The action to filter by.
            limit: Maximum number of entries to return.

        Returns:
            List of AuditLog instances ordered by created_at descending.
        """
        try:
            stmt = (
                select(AuditLog)
                .where(AuditLog.action == action)
                .order_by(AuditLog.created_at.desc())
                .limit(limit)
            )
            result = await self.session.execute(stmt)
            return list(result.scalars().all())
        except Exception as e:
            logger.error(
                "audit_log_get_by_action_error",
                action=action,
                error=str(e),
            )
            raise DatabaseError(
                message="Failed to get audit logs by action",
                operation="get_by_action",
                table="audit_logs",
                details={"action": action},
                original_error=e,
            ) from e

    async def get_recent(self, hours: int = 24, limit: int = 100) -> list[AuditLog]:
        """
        Get recent audit log entries within the specified time window.

        Args:
            hours: Number of hours to look back from now.
            limit: Maximum number of entries to return.

        Returns:
            List of AuditLog instances ordered by created_at descending.
        """
        try:
            cutoff = datetime.now(UTC) - timedelta(hours=hours)
            stmt = (
                select(AuditLog)
                .where(AuditLog.created_at >= cutoff)
                .order_by(AuditLog.created_at.desc())
                .limit(limit)
            )
            result = await self.session.execute(stmt)
            return list(result.scalars().all())
        except Exception as e:
            logger.error(
                "audit_log_get_recent_error",
                hours=hours,
                error=str(e),
            )
            raise DatabaseError(
                message="Failed to get recent audit logs",
                operation="get_recent",
                table="audit_logs",
                details={"hours": hours},
                original_error=e,
            ) from e

    async def count_by_action(self, days: int = 7) -> dict[str, int]:
        """
        Count audit log entries grouped by action over the specified number of days.

        Args:
            days: Number of days to look back.

        Returns:
            Dictionary mapping action strings to their counts.
        """
        try:
            cutoff = datetime.now(UTC) - timedelta(days=days)
            stmt = (
                select(AuditLog.action, func.count(AuditLog.id))
                .where(AuditLog.created_at >= cutoff)
                .group_by(AuditLog.action)
            )
            result = await self.session.execute(stmt)
            return {row[0]: row[1] for row in result.all()}
        except Exception as e:
            logger.error(
                "audit_log_count_by_action_error",
                days=days,
                error=str(e),
            )
            raise DatabaseError(
                message="Failed to count audit logs by action",
                operation="count_by_action",
                table="audit_logs",
                details={"days": days},
                original_error=e,
            ) from e
