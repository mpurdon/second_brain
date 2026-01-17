"""Database connection management for Second Brain agents."""

import asyncio
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Coroutine, TypeVar

import asyncpg

from .config import get_settings

T = TypeVar("T")


def run_async(coro: Coroutine[Any, Any, T]) -> T:
    """Run an async coroutine from sync code, handling Lambda environment.

    This handles the case where we're called from sync code but may or may not
    have an existing event loop. For Lambda, we always use asyncio.run() to
    ensure a fresh event loop that properly manages connection state.
    """
    # Always use asyncio.run() which creates a fresh event loop
    # This avoids issues with shared locks/pools across different loop contexts
    return asyncio.run(coro)


@asynccontextmanager
async def get_connection() -> AsyncGenerator[asyncpg.Connection, None]:
    """Get a database connection.

    Creates a fresh connection for each request. This is appropriate for Lambda
    where connection pooling across invocations is not effective.
    """
    settings = get_settings()
    conn = await asyncpg.connect(
        host=settings.database_host,
        port=settings.database_port,
        database=settings.database_name,
        user=settings.database_user,
        password=settings.database_password,
    )
    try:
        yield conn
    finally:
        await conn.close()


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
