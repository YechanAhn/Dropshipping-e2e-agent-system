"""
SQLAlchemy 2.0 async session management.
"""
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import declarative_base

from dropagent.config import get_settings
from dropagent.utils.logging import get_logger

logger = get_logger(__name__)

# Naming convention for constraints
convention = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

metadata = MetaData(naming_convention=convention)

# Declarative base for models
Base = declarative_base(metadata=metadata)

# Global engine and session maker
_engine: AsyncEngine | None = None
_async_session_maker: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """
    Get or create async database engine.

    Returns:
        AsyncEngine instance
    """
    global _engine

    if _engine is None:
        settings = get_settings()

        _engine = create_async_engine(
            str(settings.database.url),
            echo=settings.database.echo,
            pool_pre_ping=True,
            pool_size=settings.database.pool_size,
            max_overflow=settings.database.max_overflow,
        )

        logger.info(
            "database_engine_created",
            pool_size=settings.database.pool_size,
            max_overflow=settings.database.max_overflow,
        )

    return _engine


def get_session_maker() -> async_sessionmaker[AsyncSession]:
    """
    Get or create async session maker.

    Returns:
        async_sessionmaker instance
    """
    global _async_session_maker

    if _async_session_maker is None:
        engine = get_engine()
        _async_session_maker = async_sessionmaker(
            engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autocommit=False,
            autoflush=False,
        )

        logger.info("database_session_maker_created")

    return _async_session_maker


@asynccontextmanager
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Async context manager for database sessions.

    Yields:
        AsyncSession instance

    Example:
        async with get_db_session() as session:
            result = await session.execute(select(User))
            users = result.scalars().all()
    """
    session_maker = get_session_maker()
    session = session_maker()

    try:
        logger.debug("database_session_started")
        yield session
        await session.commit()
        logger.debug("database_session_committed")
    except Exception as e:
        await session.rollback()
        logger.error(
            "database_session_rollback",
            error=str(e),
            error_type=type(e).__name__,
        )
        raise
    finally:
        await session.close()
        logger.debug("database_session_closed")


async def init_db() -> None:
    """
    Initialize database tables.
    Creates all tables defined in models.
    """
    engine = get_engine()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    logger.info("database_initialized")


async def close_db() -> None:
    """
    Close database engine and cleanup connections.
    """
    global _engine, _async_session_maker

    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _async_session_maker = None

        logger.info("database_closed")
