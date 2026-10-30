"""L8 lazy async SQLAlchemy engine and durable LangGraph checkpointer factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from app.config import get_settings


def checkpointer_dsn(database_url: str) -> str:
    """Convert SQLAlchemy's asyncpg URL to the psycopg URL expected by the saver."""
    return database_url.replace("postgresql+asyncpg://", "postgresql://", 1)


def create_database_engine() -> Any:
    try:
        from sqlalchemy.ext.asyncio import create_async_engine
    except ImportError as error:
        raise RuntimeError("Install SQLAlchemy to enable PostgreSQL persistence") from error
    return create_async_engine(get_settings().database_url, pool_pre_ping=True)


@asynccontextmanager
async def postgres_checkpointer() -> AsyncIterator[Any]:
    """Yield the LangGraph PostgreSQL saver for the lifetime of an application."""
    try:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    except ImportError as error:
        raise RuntimeError("Install langgraph-checkpoint-postgres for durable workflows") from error
    async with AsyncPostgresSaver.from_conn_string(
        checkpointer_dsn(get_settings().database_url)
    ) as saver:
        await saver.setup()
        yield saver