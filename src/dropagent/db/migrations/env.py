"""
Alembic environment configuration.

Loads DATABASE_URL from .env and runs migrations
against the actual database schema defined in dropagent.db.models.
"""
import asyncio
from logging.config import fileConfig

from alembic import context
from dotenv import load_dotenv
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# Load .env before anything else
load_dotenv()

import os

# Alembic Config object
config = context.config

# Override sqlalchemy.url from environment
database_url = os.getenv("DATABASE_URL", "")
if database_url:
    # Alembic needs synchronous URL for some operations,
    # but we use async engine. Keep asyncpg as-is.
    config.set_main_option("sqlalchemy.url", database_url)

# Setup Python logging from alembic.ini
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Import all models so Alembic can detect them
from dropagent.db.models import (  # noqa: F401, E402
    AgentLog,
    AuditLog,
    Base,
    JobRun,
    Order,
    PriceHistory,
    Product,
    ProductPerformance,
    TrendData,
)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    Generates SQL script without connecting to the database.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations in 'online' mode with async engine."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
