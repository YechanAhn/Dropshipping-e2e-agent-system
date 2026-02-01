"""
Database package for DropAgent.

Re-exports session management helpers, the declarative ``Base``,
all ORM models, and repository classes so that callers can write::

    from dropagent.db import get_db_session, Product, ProductRepository
"""

# Session management
# ORM models
from dropagent.db.models import (
    AgentLog,
    AuditLog,
    Base,
    JobRun,
    Order,
    PriceHistory,
    Product,
    ProductPerformance,
    TimestampMixin,
    TrendData,
)

# Repositories
from dropagent.db.repositories import (
    AnalyticsRepository,
    AuditLogRepository,
    JobRunRepository,
    OrderRepository,
    ProductRepository,
)
from dropagent.db.session import (
    close_db,
    get_db_session,
    get_engine,
    get_session_maker,
    init_db,
)

__all__ = [
    # Session helpers
    "get_engine",
    "get_session_maker",
    "get_db_session",
    "init_db",
    "close_db",
    # Base & mixins
    "Base",
    "TimestampMixin",
    # Models
    "Product",
    "Order",
    "PriceHistory",
    "TrendData",
    "AgentLog",
    "JobRun",
    "AuditLog",
    "ProductPerformance",
    # Repositories
    "ProductRepository",
    "OrderRepository",
    "AnalyticsRepository",
    "AuditLogRepository",
    "JobRunRepository",
]
