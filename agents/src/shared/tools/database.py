"""Database tools for fact storage and retrieval."""

from datetime import date
from typing import Any
from uuid import UUID

from strands import tool

from ..database import execute_command, execute_one, execute_query, get_or_create_user, resolve_user_id, run_async
from ..models import Fact, FactCreate


@tool
def fact_store(
    content: str,
    user_id: str,
    owner_type: str = "user",
    about_entity_id: str | None = None,
    importance: int = 3,
    visibility_tier: int = 3,
    valid_from: str | None = None,
    valid_to: str | None = None,
    source: str = "text",
    tags: list[str] | None = None,
) -> dict[str, Any]:
    """Store a new fact in the knowledge base.

    Use this tool to save information the user wants to remember.
    The fact will be stored with the specified visibility tier and importance.

    Args:
        content: The fact content to store (required).
        user_id: UUID or Cognito sub of the user creating this fact.
        owner_type: Either 'user' or 'family'.
        about_entity_id: Optional UUID of the entity this fact is about.
        importance: Importance level 1-5 (5 = most important).
        visibility_tier: Access tier 1-4 (1 = most private, 4 = most visible).
        valid_from: Optional start date (YYYY-MM-DD) when fact became true.
        valid_to: Optional end date (YYYY-MM-DD) when fact stopped being true.
        source: Source of the fact: voice, text, import, calendar, or inferred.
        tags: Optional list of tag paths to apply to this fact.

    Returns:
        Dictionary with the created fact ID and status.
    """
    async def _store() -> dict[str, Any]:
        try:
            # Resolve user from various external identities (cognito_sub, discord_id, etc.)
            try:
                db_user_id, _ = await get_or_create_user(user_id, source)
            except ValueError as e:
                return {"status": "error", "message": str(e)}

            # Parse dates if provided
            parsed_valid_from = date.fromisoformat(valid_from) if valid_from else None
            parsed_valid_to = date.fromisoformat(valid_to) if valid_to else None

            # Insert the fact
            query = """
                INSERT INTO facts (
                    content, owner_type, owner_id, created_by, about_entity_id,
                    importance, visibility_tier, valid_from, valid_to,
                    source
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10::fact_source)
                RETURNING id
            """
            result = await execute_one(
                query,
                content,
                owner_type,
                db_user_id,
                db_user_id,
                UUID(about_entity_id) if about_entity_id else None,
                importance,
                visibility_tier,
                parsed_valid_from,
                parsed_valid_to,
                source,
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
        except Exception as e:
            import traceback
            return {
                "status": "error",
                "message": f"Exception in fact_store: {str(e)}",
                "traceback": traceback.format_exc(),
            }

    try:
        result = run_async(_store())
        print(f"fact_store result: {result}")
        return result
    except Exception as e:
        import traceback
        error_result = {
            "status": "error",
            "message": f"Exception running fact_store: {str(e)}",
            "traceback": traceback.format_exc(),
        }
        print(f"fact_store error: {error_result}")
        return error_result


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
        try:
            # Resolve user from various external identities (cognito_sub, discord_id, etc.)
            db_user_id, _ = await resolve_user_id(user_id)

            if not db_user_id:
                return {
                    "status": "success",
                    "count": 0,
                    "facts": [],
                    "note": "User not found in database",
                }

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
            params.append(db_user_id)
            params.append(family_uuid_list)
            param_idx = 3

            # Add optional filters
            if query_text:
                # Split query into words and match any of them for better recall
                words = [w.strip() for w in query_text.split() if w.strip()]
                if len(words) == 1:
                    # Single word - simple ILIKE
                    conditions.append(f"f.content ILIKE ${param_idx}")
                    params.append(f"%{words[0]}%")
                    param_idx += 1
                else:
                    # Multiple words - match any word (OR) for better recall
                    word_conditions = []
                    for word in words:
                        word_conditions.append(f"f.content ILIKE ${param_idx}")
                        params.append(f"%{word}%")
                        param_idx += 1
                    conditions.append(f"({' OR '.join(word_conditions)})")

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
        except Exception as e:
            import traceback
            return {
                "status": "error",
                "message": f"Exception in fact_search: {str(e)}",
                "traceback": traceback.format_exc(),
            }

    try:
        result = run_async(_search())
        print(f"fact_search result: {result}")
        return result
    except Exception as e:
        import traceback
        error_result = {
            "status": "error",
            "message": f"Exception running fact_search: {str(e)}",
            "traceback": traceback.format_exc(),
        }
        print(f"fact_search error: {error_result}")
        return error_result


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

    return run_async(_update())


@tool
def fact_update(
    fact_id: str,
    user_id: str,
    content: str | None = None,
    importance: int | None = None,
    visibility_tier: int | None = None,
    valid_from: str | None = None,
    valid_to: str | None = None,
) -> dict[str, Any]:
    """Update an existing fact in the knowledge base.

    Use this tool to correct or modify a fact's content or metadata.
    Only the fact owner can update it.

    Args:
        fact_id: UUID of the fact to update.
        user_id: UUID of the user making the request (must be owner).
        content: New content for the fact (optional).
        importance: New importance level 1-5 (optional).
        visibility_tier: New visibility tier 1-4 (optional).
        valid_from: New start date YYYY-MM-DD (optional, use "null" to clear).
        valid_to: New end date YYYY-MM-DD (optional, use "null" to clear).

    Returns:
        Dictionary with update status and updated fact.
    """
    async def _update() -> dict[str, Any]:
        try:
            # Resolve user from various external identities
            db_user_id, _ = await resolve_user_id(user_id)
            if not db_user_id:
                return {"status": "error", "message": "User not found"}

            # Build dynamic update query
            updates = []
            params: list[Any] = []
            param_idx = 1

            if content is not None:
                updates.append(f"content = ${param_idx}")
                params.append(content)
                param_idx += 1

            if importance is not None:
                if not 1 <= importance <= 5:
                    return {"status": "error", "message": "Importance must be 1-5"}
                updates.append(f"importance = ${param_idx}")
                params.append(importance)
                param_idx += 1

            if visibility_tier is not None:
                if not 1 <= visibility_tier <= 4:
                    return {"status": "error", "message": "Visibility tier must be 1-4"}
                updates.append(f"visibility_tier = ${param_idx}")
                params.append(visibility_tier)
                param_idx += 1

            if valid_from is not None:
                if valid_from.lower() == "null":
                    updates.append(f"valid_from = NULL")
                else:
                    updates.append(f"valid_from = ${param_idx}")
                    params.append(date.fromisoformat(valid_from))
                    param_idx += 1

            if valid_to is not None:
                if valid_to.lower() == "null":
                    updates.append(f"valid_to = NULL")
                else:
                    updates.append(f"valid_to = ${param_idx}")
                    params.append(date.fromisoformat(valid_to))
                    param_idx += 1

            if not updates:
                return {"status": "error", "message": "No updates provided"}

            updates.append("updated_at = NOW()")

            # Add fact_id and user_id to params
            params.append(UUID(fact_id))
            params.append(UUID(db_user_id))

            query = f"""
                UPDATE facts
                SET {', '.join(updates)}
                WHERE id = ${param_idx} AND owner_type = 'user' AND owner_id = ${param_idx + 1}
                RETURNING id, content, importance, visibility_tier, valid_from, valid_to
            """

            result = await execute_one(query, *params)

            if not result:
                return {
                    "status": "error",
                    "message": "Fact not found or you don't have permission to update it",
                }

            return {
                "status": "success",
                "fact_id": str(result["id"]),
                "updated": {
                    "content": result["content"],
                    "importance": result["importance"],
                    "visibility_tier": result["visibility_tier"],
                    "valid_from": result["valid_from"].isoformat() if result["valid_from"] else None,
                    "valid_to": result["valid_to"].isoformat() if result["valid_to"] else None,
                },
            }
        except Exception as e:
            import traceback
            return {
                "status": "error",
                "message": f"Exception in fact_update: {str(e)}",
                "traceback": traceback.format_exc(),
            }

    try:
        result = run_async(_update())
        print(f"fact_update result: {result}")
        return result
    except Exception as e:
        import traceback
        return {
            "status": "error",
            "message": f"Exception running fact_update: {str(e)}",
            "traceback": traceback.format_exc(),
        }


@tool
def fact_delete(
    fact_id: str,
    user_id: str,
) -> dict[str, Any]:
    """Delete a fact from the knowledge base.

    Use this tool to remove incorrect or unwanted facts.
    Only the fact owner can delete it.

    Args:
        fact_id: UUID of the fact to delete.
        user_id: UUID of the user making the request (must be owner).

    Returns:
        Dictionary with deletion status.
    """
    async def _delete() -> dict[str, Any]:
        try:
            # Resolve user from various external identities
            db_user_id, _ = await resolve_user_id(user_id)
            if not db_user_id:
                return {"status": "error", "message": "User not found"}

            # First get the fact content for confirmation
            fact = await execute_one(
                """
                SELECT id, content FROM facts
                WHERE id = $1 AND owner_type = 'user' AND owner_id = $2
                """,
                UUID(fact_id),
                UUID(db_user_id),
            )

            if not fact:
                return {
                    "status": "error",
                    "message": "Fact not found or you don't have permission to delete it",
                }

            # Delete related records first (foreign keys)
            await execute_command(
                "DELETE FROM fact_tags WHERE fact_id = $1",
                UUID(fact_id),
            )
            await execute_command(
                "DELETE FROM entity_mentions WHERE fact_id = $1",
                UUID(fact_id),
            )

            # Delete the fact
            await execute_command(
                "DELETE FROM facts WHERE id = $1",
                UUID(fact_id),
            )

            return {
                "status": "success",
                "message": f"Deleted fact: {fact['content'][:50]}...",
                "deleted_fact_id": fact_id,
            }
        except Exception as e:
            import traceback
            return {
                "status": "error",
                "message": f"Exception in fact_delete: {str(e)}",
                "traceback": traceback.format_exc(),
            }

    try:
        result = run_async(_delete())
        print(f"fact_delete result: {result}")
        return result
    except Exception as e:
        import traceback
        return {
            "status": "error",
            "message": f"Exception running fact_delete: {str(e)}",
            "traceback": traceback.format_exc(),
        }


@tool
def user_link_external_identity(
    cognito_sub: str,
    identity_type: str,
    identity_value: str,
) -> dict[str, Any]:
    """Link an external identity (Discord, Alexa) to a user account.

    Use this tool to connect external platform identities to Cognito users.
    This allows Discord/Alexa users to access their Second Brain data.

    Args:
        cognito_sub: The Cognito sub of the user to link.
        identity_type: Type of identity: 'discord' or 'alexa'.
        identity_value: The external identity value (Discord ID, Alexa User ID).

    Returns:
        Dictionary with link status.
    """
    async def _link() -> dict[str, Any]:
        if identity_type not in ("discord", "alexa"):
            return {
                "status": "error",
                "message": f"Invalid identity type: {identity_type}. Must be 'discord' or 'alexa'.",
            }

        column = f"{identity_type}_id" if identity_type == "discord" else "alexa_user_id"

        result = await execute_one(
            f"""
            UPDATE users
            SET {column} = $1
            WHERE cognito_sub = $2
            RETURNING id, cognito_sub, {column}
            """,
            identity_value,
            cognito_sub,
        )

        if not result:
            return {
                "status": "error",
                "message": f"User with cognito_sub {cognito_sub} not found",
            }

        return {
            "status": "success",
            "user_id": str(result["id"]),
            "cognito_sub": result["cognito_sub"],
            identity_type + "_id": result[column],
        }

    return run_async(_link())
