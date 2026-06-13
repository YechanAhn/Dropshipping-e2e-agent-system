"""
Shared FastAPI dependencies for the DropAgent API.

Provides an async database-session dependency plus thin repository factory
dependencies. The session dependency yields an ``AsyncSession`` built from the
global session maker; in tests these are replaced via
``app.dependency_overrides`` so no real database is required.
"""
from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from dropagent.db.repositories.analytics_repo import AnalyticsRepository
from dropagent.db.repositories.order_repo import OrderRepository
from dropagent.db.repositories.product_repo import ProductRepository
from dropagent.db.session import get_session_maker


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency that yields an async database session.

    Commits on success and rolls back on error, mirroring
    ``dropagent.db.session.get_db_session``. Overridable in tests.

    Yields:
        AsyncSession: An active SQLAlchemy async session.
    """
    session_maker = get_session_maker()
    session = session_maker()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


SessionDep = Annotated[AsyncSession, Depends(get_session)]


def get_product_repo(session: SessionDep) -> ProductRepository:
    """Provide a ``ProductRepository`` bound to the request session."""
    return ProductRepository(session)


def get_order_repo(session: SessionDep) -> OrderRepository:
    """Provide an ``OrderRepository`` bound to the request session."""
    return OrderRepository(session)


def get_analytics_repo(session: SessionDep) -> AnalyticsRepository:
    """Provide an ``AnalyticsRepository`` bound to the request session."""
    return AnalyticsRepository(session)


ProductRepoDep = Annotated[ProductRepository, Depends(get_product_repo)]
OrderRepoDep = Annotated[OrderRepository, Depends(get_order_repo)]
AnalyticsRepoDep = Annotated[AnalyticsRepository, Depends(get_analytics_repo)]
