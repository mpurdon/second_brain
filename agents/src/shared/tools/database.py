"""Database tools for fact storage and retrieval."""

import asyncio
from datetime import date
from typing import Any
from uuid import UUID

from strands import tool

from ..database import execute_command, execute_one, execute_query
from ..models import Fact, FactCreate


@tool
def fact_store(
    content: str,
    owner_id: str,
    owner_type: str = "user",
    about_entity_id: str | None = None,
    importance: int = 3,
    visibility_tier: int = 3,
    valid_from: str | None = None,
    valid_to: str | None = None,
    source_type: str = "voice",
    tags: list[str] | None = None,
) -> dict[str, Any]:
    """Store a new fact in the knowledge base.

    Use this tool to save information the user wants to remember.
    The fact will be stored with the specified visibility tier and importance.

    Args:
        content: The fact content to store (required).
        owner_id: UUID of the user or family that owns this fact.
        owner_type: Either 'user' or 'family'.
        about_entity_id: Optional UUID of the entity this fact is about.
        importance: Importance level 1-5 (5 = most important).
        visibility_tier: Access tier 1-4 (1 = most private, 4 = most visible).
        valid_from: Optional start date (YYYY-MM-DD) when fact became true.
        valid_to: Optional end date (YYYY-MM-DD) when fact stopped being true.
        source_type: Source of the fact: voice, text, import, or calendar.
        tags: Optional list of tag paths to apply to this fact.

    Returns:
        Dictionary with the created fact ID and status.
    """
    async def _store() -> dict[str, Any]:
        # Parse dates if provided
        parsed_valid_from = date.fromisoformat(valid_from) if valid_from else None
        parsed_valid_to = date.fromisoformat(valid_to) if valid_to else None

        # Insert the fact
        query = """
            INSERT INTO facts (
                content, owner_type, owner_id, about_entity_id,
                importance, visibility_tier, valid_from, valid_to,
                source_type
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            RETURNING id
        """
        result = await execute_one(
            query,
            content,
            owner_type,
            UUID(owner_id),
            UUID(about_entity_id) if about_entity_id else None,
            importance,
            visibility_tier,
            parsed_valid_from,
            parsed_valid_to,
            source_type,
        )

        if not result:
            return {"status": "error", "message": "Failed to store fact"}

        fact_id = result["id"]

        # Apply tags if provided
        if tags:
            for tag_path in tags:
                await execute_command(
                    """
                    INSERT INTO fact_tags (fact_id, tag_id)
                    SELECT $1, id FROM tags WHERE path = $2
                    ON CONFLICT DO NOTHING
                    """,
                    fact_id,
                    tag_path,
                )

        return {
            "status": "success",
            "fact_id": str(fact_id),
            "message": f"Stored fact with ID {fact_id}",
        }

    return asyncio.get_event_loop().run_until_complete(_store())


@tool
def fact_search(
    user_id: str,
    query_text: str | None = None,
    family_ids: list[str] | None = None,
    entity_id: str | None = None,
    tags: list[str] | None = None,
    importance_min: int | None = None,
    valid_at: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Search for facts in the knowledge base with permission filtering.

    Use this tool to find facts based on various criteria.
    Results are filtered by the user's access permissions including:
    - User's own facts (always visible)
    - Facts from related users (filtered by visibility tier)
    - Family-owned facts (visible to family members)

    Args:
        user_id: UUID of the user performing the search.
        query_text: Optional text to search for in fact content.
        family_ids: Optional list of family UUIDs to include in search scope.
        entity_id: Optional UUID to filter facts about a specific entity.
        tags: Optional list of tag paths to filter by.
        importance_min: Optional minimum importance level (1-5).
        valid_at: Optional date (YYYY-MM-DD) for point-in-time query.
        limit: Maximum number of results to return (default 20).

    Returns:
        Dictionary with list of matching facts.
    """
    async def _search() -> dict[str, Any]:
        conditions = ["1=1"]
        params: list[Any] = []

        # Build family IDs array
        family_uuid_list = [UUID(fid) for fid in (family_ids or [])]

        # Permission-aware base query
        # Handles user facts, related user facts, and family facts
        base_query = """
            SELECT f.id, f.content, f.importance, f.visibility_tier,
                   f.recorded_at, f.valid_from, f.valid_to,
                   f.owner_type, f.owner_id,
                   e.name as entity_name
            FROM facts f
            LEFT JOIN entities e ON e.id = f.about_entity_id
            LEFT JOIN user_access_cache uac
                ON f.owner_type = 'user'
                AND f.owner_id = uac.target_user_id
                AND uac.viewer_user_id = $1
            WHERE (
                -- User's own facts
                (f.owner_type = 'user' AND f.owner_id = $1)
                -- Facts from related users (with permission check)
                OR (f.owner_type = 'user' AND uac.access_tier IS NOT NULL AND uac.access_tier <= f.visibility_tier)
                -- Family-owned facts (if user is in that family)
                OR (f.owner_type = 'family' AND f.owner_id = ANY($2::uuid[]))
            )
        """
        params.append(UUID(user_id))
        params.append(family_uuid_list)
        param_idx = 3

        # Add optional filters
        if query_text:
            conditions.append(f"f.content ILIKE ${param_idx}")
            params.append(f"%{query_text}%")
            param_idx += 1

        if entity_id:
            conditions.append(f"f.about_entity_id = ${param_idx}")
            params.append(UUID(entity_id))
            param_idx += 1

        if importance_min:
            conditions.append(f"f.importance >= ${param_idx}")
            params.append(importance_min)
            param_idx += 1

        if valid_at:
            parsed_date = date.fromisoformat(valid_at)
            conditions.append(
                f"(f.valid_from IS NULL OR f.valid_from <= ${param_idx})"
            )
            params.append(parsed_date)
            param_idx += 1
            conditions.append(
                f"(f.valid_to IS NULL OR f.valid_to > ${param_idx})"
            )
            params.append(parsed_date)
            param_idx += 1

        if tags:
            conditions.append(f"""
                f.id IN (
                    SELECT ft.fact_id FROM fact_tags ft
                    JOIN tags t ON t.id = ft.tag_id
                    WHERE t.path = ANY(${param_idx}::text[])
                )
            """)
            params.append(tags)
            param_idx += 1

        # Build final query
        where_clause = " AND ".join(conditions)
        final_query = f"""
            {base_query}
            AND {where_clause}
            ORDER BY f.importance DESC, f.recorded_at DESC
            LIMIT ${param_idx}
        """
        params.append(limit)

        results = await execute_query(final_query, *params)

        facts = [
            {
                "id": str(row["id"]),
                "content": row["content"],
                "importance": row["importance"],
                "visibility_tier": row["visibility_tier"],
                "recorded_at": row["recorded_at"].isoformat(),
                "valid_from": row["valid_from"].isoformat() if row["valid_from"] else None,
                "valid_to": row["valid_to"].isoformat() if row["valid_to"] else None,
                "entity_name": row["entity_name"],
                "owner_type": row["owner_type"],
            }
            for row in results
        ]

        return {
            "status": "success",
            "count": len(facts),
            "facts": facts,
        }

    return asyncio.get_event_loop().run_until_complete(_search())


@tool
def fact_update_visibility(
    fact_id: str,
    user_id: str,
    visibility_tier: int,
) -> dict[str, Any]:
    """Update the visibility tier of a fact.

    Use this tool to change who can see a specific fact.
    Only the fact owner can update visibility.

    Args:
        fact_id: UUID of the fact to update.
        user_id: UUID of the user making the request (must be owner).
        visibility_tier: New visibility tier (1-4).
            1 = Private (only owner)
            2 = Close family (spouse, parents)
            3 = Extended family
            4 = All connections

    Returns:
        Dictionary with update status.
    """
    async def _update() -> dict[str, Any]:
        if not 1 <= visibility_tier <= 4:
            return {
                "status": "error",
                "message": "Visibility tier must be between 1 and 4",
            }

        # Update only if user owns the fact
        result = await execute_one(
            """
            UPDATE facts
            SET visibility_tier = $1, updated_at = NOW()
            WHERE id = $2 AND owner_type = 'user' AND owner_id = $3
            RETURNING id
            """,
            visibility_tier,
            UUID(fact_id),
            UUID(user_id),
        )

        if not result:
            return {
                "status": "error",
                "message": "Fact not found or you don't have permission to update it",
            }

        return {
            "status": "success",
            "fact_id": fact_id,
            "new_visibility_tier": visibility_tier,
        }

    return asyncio.get_event_loop().run_until_complete(_update())
