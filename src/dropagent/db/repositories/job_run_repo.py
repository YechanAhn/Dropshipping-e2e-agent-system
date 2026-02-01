"""
Job Run Repository - Database operations for the JobRun model (idempotent job tracking).
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from dropagent.db.models import JobRun
from dropagent.utils.exceptions import DatabaseError
from dropagent.utils.logging import get_logger

logger = get_logger(__name__)


class JobRunRepository:
    """Repository for idempotent job run tracking and management."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        idempotency_key: str,
        job_type: str,
        input_params: dict | None = None,
    ) -> JobRun:
        """
        Create a new job run entry with 'running' status.

        Args:
            idempotency_key: Unique key to prevent duplicate execution.
            job_type: Type/name of the job.
            input_params: Optional JSON-serializable input parameters.

        Returns:
            The newly created JobRun instance.

        Raises:
            DatabaseError: On duplicate idempotency_key or other DB errors.
        """
        try:
            job_run = JobRun(
                idempotency_key=idempotency_key,
                job_type=job_type,
                status="running",
                input_params=input_params,
                started_at=datetime.now(UTC),
            )
            self.session.add(job_run)
            await self.session.flush()
            await self.session.refresh(job_run)
            logger.info(
                "job_run_created",
                idempotency_key=idempotency_key,
                job_type=job_type,
            )
            return job_run
        except IntegrityError as e:
            await self.session.rollback()
            logger.warning(
                "job_run_create_duplicate",
                idempotency_key=idempotency_key,
                error=str(e),
            )
            raise DatabaseError(
                message=f"Job run with idempotency key '{idempotency_key}' already exists",
                operation="create",
                table="job_runs",
                details={"idempotency_key": idempotency_key},
                original_error=e,
            ) from e
        except Exception as e:
            await self.session.rollback()
            logger.error(
                "job_run_create_error",
                idempotency_key=idempotency_key,
                error=str(e),
            )
            raise DatabaseError(
                message="Failed to create job run",
                operation="create",
                table="job_runs",
                original_error=e,
            ) from e

    async def get_by_key(self, idempotency_key: str) -> JobRun | None:
        """
        Look up a job run by its idempotency key.

        Args:
            idempotency_key: The unique job key.

        Returns:
            JobRun instance or None if not found.
        """
        try:
            stmt = select(JobRun).where(JobRun.idempotency_key == idempotency_key)
            result = await self.session.execute(stmt)
            return result.scalar_one_or_none()
        except Exception as e:
            logger.error(
                "job_run_get_by_key_error",
                idempotency_key=idempotency_key,
                error=str(e),
            )
            raise DatabaseError(
                message="Failed to get job run by key",
                operation="get_by_key",
                table="job_runs",
                details={"idempotency_key": idempotency_key},
                original_error=e,
            ) from e

    async def update_status(
        self,
        idempotency_key: str,
        status: str,
        output_result: dict | None = None,
        error_message: str | None = None,
    ) -> JobRun:
        """
        Update the status of a job run.

        When transitioning to 'completed' or 'failed', the completed_at timestamp
        is set automatically.

        Args:
            idempotency_key: The unique job key.
            status: New status ('running', 'completed', or 'failed').
            output_result: Optional output data (typically set on completion).
            error_message: Optional error message (typically set on failure).

        Returns:
            The updated JobRun instance.

        Raises:
            DatabaseError: If the job run is not found or the update fails.
        """
        try:
            job_run = await self.get_by_key(idempotency_key)
            if job_run is None:
                raise DatabaseError(
                    message=f"Job run with key '{idempotency_key}' not found",
                    operation="update_status",
                    table="job_runs",
                    details={"idempotency_key": idempotency_key},
                )

            job_run.status = status
            if output_result is not None:
                job_run.output_result = output_result
            if error_message is not None:
                job_run.error_message = error_message
            if status in ("completed", "failed"):
                job_run.completed_at = datetime.now(UTC)

            await self.session.flush()
            await self.session.refresh(job_run)
            logger.info(
                "job_run_status_updated",
                idempotency_key=idempotency_key,
                new_status=status,
            )
            return job_run
        except DatabaseError:
            raise
        except Exception as e:
            await self.session.rollback()
            logger.error(
                "job_run_update_status_error",
                idempotency_key=idempotency_key,
                status=status,
                error=str(e),
            )
            raise DatabaseError(
                message="Failed to update job run status",
                operation="update_status",
                table="job_runs",
                details={"idempotency_key": idempotency_key, "status": status},
                original_error=e,
            ) from e

    async def list_running(self) -> list[JobRun]:
        """
        List all currently running job runs.

        Returns:
            List of JobRun instances with status 'running'.
        """
        try:
            stmt = (
                select(JobRun)
                .where(JobRun.status == "running")
                .order_by(JobRun.started_at.asc())
            )
            result = await self.session.execute(stmt)
            return list(result.scalars().all())
        except Exception as e:
            logger.error(
                "job_run_list_running_error",
                error=str(e),
            )
            raise DatabaseError(
                message="Failed to list running job runs",
                operation="list_running",
                table="job_runs",
                original_error=e,
            ) from e

    async def list_failed(self, limit: int = 50) -> list[JobRun]:
        """
        List failed job runs, most recent first.

        Args:
            limit: Maximum number of failed runs to return.

        Returns:
            List of JobRun instances with status 'failed'.
        """
        try:
            stmt = (
                select(JobRun)
                .where(JobRun.status == "failed")
                .order_by(JobRun.completed_at.desc().nulls_last())
                .limit(limit)
            )
            result = await self.session.execute(stmt)
            return list(result.scalars().all())
        except Exception as e:
            logger.error(
                "job_run_list_failed_error",
                limit=limit,
                error=str(e),
            )
            raise DatabaseError(
                message="Failed to list failed job runs",
                operation="list_failed",
                table="job_runs",
                original_error=e,
            ) from e

    async def cleanup_stale(self, hours: int = 24) -> int:
        """
        Mark stale 'running' jobs as 'failed'.

        Jobs that have been running longer than the specified hours are considered
        stale and are transitioned to 'failed' with an appropriate error message.

        Args:
            hours: Number of hours after which a running job is considered stale.

        Returns:
            The number of jobs marked as failed.
        """
        try:
            cutoff = datetime.now(UTC) - timedelta(hours=hours)
            stmt = (
                update(JobRun)
                .where(JobRun.status == "running")
                .where(JobRun.started_at < cutoff)
                .values(
                    status="failed",
                    error_message=f"Job marked as failed: stale after {hours} hours",
                    completed_at=datetime.now(UTC),
                )
            )
            result = await self.session.execute(stmt)
            await self.session.flush()
            count = result.rowcount
            if count > 0:
                logger.warning(
                    "stale_jobs_cleaned_up",
                    count=count,
                    stale_threshold_hours=hours,
                )
            return count
        except Exception as e:
            await self.session.rollback()
            logger.error(
                "job_run_cleanup_stale_error",
                hours=hours,
                error=str(e),
            )
            raise DatabaseError(
                message="Failed to clean up stale job runs",
                operation="cleanup_stale",
                table="job_runs",
                details={"hours": hours},
                original_error=e,
            ) from e

    async def increment_retry(self, idempotency_key: str) -> JobRun:
        """
        Increment the retry count for a job run and reset status to 'running'.

        Args:
            idempotency_key: The unique job key.

        Returns:
            The updated JobRun instance with incremented retry_count.

        Raises:
            DatabaseError: If the job run is not found or the update fails.
        """
        try:
            job_run = await self.get_by_key(idempotency_key)
            if job_run is None:
                raise DatabaseError(
                    message=f"Job run with key '{idempotency_key}' not found",
                    operation="increment_retry",
                    table="job_runs",
                    details={"idempotency_key": idempotency_key},
                )

            job_run.retry_count = job_run.retry_count + 1
            job_run.status = "running"
            job_run.error_message = None
            job_run.completed_at = None
            job_run.started_at = datetime.now(UTC)

            await self.session.flush()
            await self.session.refresh(job_run)
            logger.info(
                "job_run_retry_incremented",
                idempotency_key=idempotency_key,
                retry_count=job_run.retry_count,
            )
            return job_run
        except DatabaseError:
            raise
        except Exception as e:
            await self.session.rollback()
            logger.error(
                "job_run_increment_retry_error",
                idempotency_key=idempotency_key,
                error=str(e),
            )
            raise DatabaseError(
                message="Failed to increment job retry count",
                operation="increment_retry",
                table="job_runs",
                details={"idempotency_key": idempotency_key},
                original_error=e,
            ) from e
