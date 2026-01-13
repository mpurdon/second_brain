"""Database connection management for Second Brain agents."""

import asyncio
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator

import asyncpg

from .config import get_settings


class DatabasePool:
    """Async PostgreSQL connection pool manager."""

    _pool: asyncpg.Pool | None = None
    _lock: asyncio.Lock = asyncio.Lock()

    @classmethod
    async def get_pool(cls) -> asyncpg.Pool:
        """Get or create the connection pool."""
        if cls._pool is None:
            async with cls._lock:
                if cls._pool is None:
                    settings = get_settings()
                    cls._pool = await asyncpg.create_pool(
                        host=settings.database_host,
                        port=settings.database_port,
                        database=settings.database_name,
                        user=settings.database_user,
                        password=settings.database_password,
                        min_size=1,
                        max_size=10,
                    )
        return cls._pool

    @classmethod
    async def close(cls) -> None:
        """Close the connection pool."""
        if cls._pool is not None:
            await cls._pool.close()
            cls._pool = None


@asynccontextmanager
async def get_connection() -> AsyncGenerator[asyncpg.Connection, None]:
    """Get a database connection from the pool."""
    pool = await DatabasePool.get_pool()
    async with pool.acquire() as conn:
        yield conn


async def execute_query(
    query: str,
    *args: Any,
) -> list[asyncpg.Record]:
    """Execute a query and return results."""
    async with get_connection() as conn:
        return await conn.fetch(query, *args)


async def execute_one(
    query: str,
    *args: Any,
) -> asyncpg.Record | None:
    """Execute a query and return a single result."""
    async with get_connection() as conn:
        return await conn.fetchrow(query, *args)


async def execute_scalar(
    query: str,
    *args: Any,
) -> Any:
    """Execute a query and return a scalar value."""
    async with get_connection() as conn:
        return await conn.fetchval(query, *args)


async def execute_command(
    query: str,
    *args: Any,
) -> str:
    """Execute a command (INSERT, UPDATE, DELETE) and return status."""
    async with get_connection() as conn:
        return await conn.execute(query, *args)
