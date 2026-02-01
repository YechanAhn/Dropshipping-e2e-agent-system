"""
Job Run Model (Idempotency)
"""
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from . import Base


class JobRun(Base):
    """Job run table for idempotent job execution tracking"""

    __tablename__ = "job_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    # Idempotency key
    idempotency_key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)

    # Job information
    job_type: Mapped[str] = mapped_column(String(100), nullable=False)

    # Status: running, completed, failed
    status: Mapped[str] = mapped_column(String(50), nullable=False)

    # Input and output as JSONB
    input_params: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    output_result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    # Error handling
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    # Timestamps
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Check constraint for status
    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'completed', 'failed')",
            name="check_job_run_status"
        ),
    )

    def __repr__(self) -> str:
        return f"<JobRun(id={self.id}, idempotency_key={self.idempotency_key}, status={self.status})>"
