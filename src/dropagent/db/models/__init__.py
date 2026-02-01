"""
SQLAlchemy 2.0 Database Models
"""
from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base class for all database models"""
    pass


class TimestampMixin:
    """Mixin for created_at and updated_at timestamps"""
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False
    )


# Import all models (after Base/TimestampMixin are defined to avoid circular imports)
from .agent_log import AgentLog  # noqa: E402
from .audit_log import AuditLog  # noqa: E402
from .job_run import JobRun  # noqa: E402
from .order import Order  # noqa: E402
from .price_history import PriceHistory  # noqa: E402
from .product import Product  # noqa: E402
from .product_performance import ProductPerformance  # noqa: E402
from .trend_data import TrendData  # noqa: E402

__all__ = [
    "Base",
    "TimestampMixin",
    "Product",
    "Order",
    "PriceHistory",
    "TrendData",
    "AgentLog",
    "JobRun",
    "AuditLog",
    "ProductPerformance",
]
