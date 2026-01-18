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


async def resolve_user_id(external_id: str) -> tuple[str | None, str | None]:
    """Resolve a user's database ID from various external identifiers.

    Tries to find the user by:
    1. cognito_sub
    2. discord_id
    3. alexa_user_id

    Args:
        external_id: The external identifier (Cognito sub, Discord ID, etc.)

    Returns:
        Tuple of (database_user_id, cognito_sub) or (None, None) if not found.
    """
    # Try cognito_sub first
    user = await execute_one(
        "SELECT id, cognito_sub FROM users WHERE cognito_sub = $1::varchar",
        external_id,
    )
    if user:
        return str(user["id"]), user["cognito_sub"]

    # Try discord_id
    user = await execute_one(
        "SELECT id, cognito_sub FROM users WHERE discord_id = $1::varchar",
        external_id,
    )
    if user:
        return str(user["id"]), user["cognito_sub"]

    # Try alexa_user_id
    user = await execute_one(
        "SELECT id, cognito_sub FROM users WHERE alexa_user_id = $1::varchar",
        external_id,
    )
    if user:
        return str(user["id"]), user["cognito_sub"]

    return None, None


async def get_or_create_user(external_id: str, source: str = "api") -> tuple[str, str]:
    """Get or create a user by external identifier.

    First tries to resolve the user by various external IDs.
    If not found and source is 'discord' or 'alexa', returns an error.
    Otherwise, creates a new user with the external_id as cognito_sub.

    Args:
        external_id: The external identifier.
        source: The source of the request ('api', 'discord', 'alexa').

    Returns:
        Tuple of (database_user_id, cognito_sub).

    Raises:
        ValueError: If user not found and source doesn't support auto-creation.
    """
    # Try to find existing user
    db_id, cognito_sub = await resolve_user_id(external_id)
    if db_id:
        return db_id, cognito_sub

    # For Discord/Alexa, require pre-linked accounts
    if source in ("discord", "alexa"):
        raise ValueError(
            f"No account linked for {source} user {external_id}. "
            "Please link your account first."
        )

    # Auto-create user for API requests (Cognito-authenticated)
    user = await execute_one(
        """
        INSERT INTO users (cognito_sub, email, display_name)
        VALUES ($1::varchar, $2, 'User')
        ON CONFLICT (cognito_sub) DO UPDATE SET cognito_sub = users.cognito_sub
        RETURNING id, cognito_sub
        """,
        external_id,
        f"{external_id}@placeholder.local",
    )

    if user:
        return str(user["id"]), user["cognito_sub"]

    raise ValueError(f"Failed to create user for {external_id}")


async def reset_knowledge_base() -> dict:
    """Reset knowledge base data while preserving setup.

    Clears: facts, entities, conversations, messages
    Keeps: users, families, tags, calendar_subscriptions, external identities

    Returns:
        Dictionary with counts of remaining records.
    """
    async with get_connection() as conn:
        # Clear fact-related data (order matters due to foreign keys)
        await conn.execute("TRUNCATE TABLE fact_tags CASCADE")
        await conn.execute("TRUNCATE TABLE entity_mentions CASCADE")
        await conn.execute("TRUNCATE TABLE facts CASCADE")

        # Clear entity-related data
        await conn.execute("TRUNCATE TABLE entity_relationships CASCADE")
        await conn.execute("TRUNCATE TABLE entity_locations CASCADE")
        await conn.execute("TRUNCATE TABLE entity_attributes CASCADE")
        await conn.execute("TRUNCATE TABLE entities CASCADE")

        # Clear conversation data
        await conn.execute("TRUNCATE TABLE messages CASCADE")
        await conn.execute("TRUNCATE TABLE conversations CASCADE")

        # Get counts of what remains
        users = await conn.fetchval("SELECT COUNT(*) FROM users")
        tags = await conn.fetchval("SELECT COUNT(*) FROM tags")
        facts = await conn.fetchval("SELECT COUNT(*) FROM facts")
        entities = await conn.fetchval("SELECT COUNT(*) FROM entities")

        return {
            "status": "success",
            "message": "Knowledge base reset complete",
            "remaining": {
                "users": users,
                "tags": tags,
                "facts": facts,
                "entities": entities,
            }
        }
