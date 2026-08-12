"""Async Alembic environment for NeuralRAG.

The application owns configuration through ``app.config.settings``.  Using it
here means ``DATABASE_URL`` behaves identically for Alembic, Uvicorn, workers,
and Docker deployments, without committing a connection string to alembic.ini.
"""
from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.config import async_database_url, settings
from app.models.database import Base


config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# This also imports every mapped model through database.py, keeping autogenerate
# accurate when future migrations are created.
target_metadata = Base.metadata


def _configured_url() -> str:
    """Use the same URL conversion as the app's async SQLAlchemy engine."""
    return async_database_url(settings.DATABASE_URL)


def run_migrations_offline() -> None:
    context.configure(
        url=_configured_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = _configured_url()
    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
