"""Entity management tools for Second Brain agents."""

from typing import Any
from uuid import UUID

from strands import tool

from ..database import execute_command, execute_one, execute_query, get_or_create_user, resolve_user_id, run_async


@tool
def entity_search(
    user_id: str,
    query: str | None = None,
    entity_type: str | None = None,
    relationship: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Search for entities in the knowledge base.

    Use this tool to find people, organizations, places, projects, or events.
    Supports fuzzy matching on names and filtering by relationship to user.

    Args:
        user_id: UUID of the user performing the search.
        query: Optional text to search for in entity names.
        entity_type: Optional filter by type (person, organization, place, project, event).
        relationship: Optional filter by relationship to user (e.g., "granddaughter", "father", "friend").
                     When querying "who is my granddaughter?", use relationship="granddaughter".
        limit: Maximum number of results to return (default 20).

    Returns:
        Dictionary with list of matching entities.
    """
    async def _search() -> dict[str, Any]:
        try:
            # Resolve user from various external identities (cognito_sub, discord_id, etc.)
            db_user_id, _ = await resolve_user_id(user_id)

            if not db_user_id:
                return {
                    "status": "success",
                    "count": 0,
                    "entities": [],
                    "note": "User not found in database",
                }

            conditions = []
            params: list[Any] = [db_user_id]
            param_idx = 2

            # Base query with ownership check
            base_query = """
                SELECT e.id, e.entity_type::text, e.name, e.normalized_name,
                       e.metadata, e.created_at,
                       COUNT(f.id) as fact_count
                FROM entities e
                LEFT JOIN facts f ON f.about_entity_id = e.id
                WHERE (
                    (e.owner_type = 'user' AND e.owner_id = $1)
                    OR e.owner_type = 'family'
                )
            """

            if query:
                # Use pg_trgm for fuzzy matching
                conditions.append(f"(e.name ILIKE ${param_idx} OR e.normalized_name ILIKE ${param_idx})")
                params.append(f"%{query}%")
                param_idx += 1

            if entity_type:
                conditions.append(f"e.entity_type = ${param_idx}::entity_type")
                params.append(entity_type)
                param_idx += 1

            if relationship:
                # Search for entities with this relationship in metadata
                conditions.append(f"e.metadata->>'relationship_to_user' ILIKE ${param_idx}")
                params.append(f"%{relationship}%")
                param_idx += 1

            where_clause = " AND ".join(conditions) if conditions else "1=1"
            final_query = f"""
                {base_query}
                AND {where_clause}
                GROUP BY e.id
                ORDER BY fact_count DESC, e.name ASC
                LIMIT ${param_idx}
            """
            params.append(limit)

            results = await execute_query(final_query, *params)

            entities = []
            for row in results:
                # Handle metadata - it might be a dict, string, or None
                metadata = row["metadata"]
                if metadata is None:
                    metadata_dict = {}
                elif isinstance(metadata, dict):
                    metadata_dict = metadata
                elif hasattr(metadata, 'items'):
                    metadata_dict = dict(metadata)
                else:
                    metadata_dict = {}

                entities.append({
                    "id": str(row["id"]),
                    "entity_type": row["entity_type"],
                    "name": row["name"],
                    "normalized_name": row["normalized_name"],
                    "metadata": metadata_dict,
                    "fact_count": row["fact_count"],
                    "created_at": row["created_at"].isoformat(),
                })

            return {
                "status": "success",
                "count": len(entities),
                "entities": entities,
            }
        except Exception as e:
            import traceback
            return {
                "status": "error",
                "message": f"Exception in entity_search: {str(e)}",
                "traceback": traceback.format_exc(),
            }

    try:
        result = run_async(_search())
        print(f"entity_search result: {result}")
        return result
    except Exception as e:
        import traceback
        error_result = {
            "status": "error",
            "message": f"Exception running entity_search: {str(e)}",
            "traceback": traceback.format_exc(),
        }
        print(f"entity_search error: {error_result}")
        return error_result


@tool
def entity_create(
    name: str,
    entity_type: str,
    user_id: str,
    owner_type: str = "user",
    description: str | None = None,
    aliases: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    visibility_tier: int = 3,
) -> dict[str, Any]:
    """Create a new entity in the knowledge base.

    Use this tool to create a new person, organization, place, project, or event.
    Entities are used to organize facts and relationships.

    Args:
        name: Display name for the entity (required).
        entity_type: Type of entity (person, organization, place, project, event, product, custom).
        user_id: Cognito sub of the user creating this entity.
        owner_type: Either 'user' or 'family'.
        description: Optional description of the entity.
        aliases: Optional list of alternative names for the entity.
        metadata: Optional dictionary of additional metadata.
        visibility_tier: Visibility tier 1-4 (default 3).

    Returns:
        Dictionary with the created entity ID and details.
    """
    async def _create() -> dict[str, Any]:
        import json

        try:
            # Resolve user from various external identities (cognito_sub, discord_id, etc.)
            try:
                db_user_id, _ = await get_or_create_user(user_id, "api")
            except ValueError as e:
                return {"status": "error", "message": str(e)}

            metadata_json = json.dumps(metadata or {})
            alias_list = aliases or []

            result = await execute_one(
                """
                INSERT INTO entities (entity_type, name, description, aliases, owner_type, owner_id, created_by, metadata, visibility_tier)
                VALUES ($1::entity_type, $2, $3, $4, $5, $6, $7, $8::jsonb, $9)
                RETURNING id, normalized_name, created_at
                """,
                entity_type,
                name,
                description,
                alias_list,
                owner_type,
                db_user_id,
                db_user_id,
                metadata_json,
                visibility_tier,
            )

            if not result:
                return {"status": "error", "message": "Failed to create entity"}

            return {
                "status": "success",
                "entity_id": str(result["id"]),
                "name": name,
                "entity_type": entity_type,
                "normalized_name": result["normalized_name"],
                "created_at": result["created_at"].isoformat(),
            }
        except Exception as e:
            import traceback
            return {
                "status": "error",
                "message": f"Exception in entity_create: {str(e)}",
                "traceback": traceback.format_exc(),
            }

    try:
        result = run_async(_create())
        print(f"entity_create result: {result}")
        return result
    except Exception as e:
        import traceback
        error_result = {
            "status": "error",
            "message": f"Exception running entity_create: {str(e)}",
            "traceback": traceback.format_exc(),
        }
        print(f"entity_create error: {error_result}")
        return error_result


@tool
def entity_get_details(
    user_id: str,
    entity_id: str,
    family_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Get detailed information about an entity.

    Use this tool to retrieve complete information about an entity,
    including all its attributes, locations, relationships, and recent facts.

    Args:
        user_id: UUID of the user requesting the information.
        entity_id: UUID of the entity to retrieve.
        family_ids: Optional list of family IDs the user belongs to.

    Returns:
        Dictionary with entity details, locations, relationships, and related facts.
    """
    async def _get_details() -> dict[str, Any]:
        try:
            # Resolve user from various external identities (cognito_sub, discord_id, etc.)
            db_user_id, _ = await resolve_user_id(user_id)

            if not db_user_id:
                return {
                    "status": "error",
                    "message": "User not found in database",
                }

            family_uuid_list = [UUID(fid) for fid in (family_ids or [])]

            # Get entity details
            entity = await execute_one(
                """
                SELECT e.id, e.entity_type::text, e.name, e.normalized_name, e.description,
                       e.aliases, e.owner_type, e.owner_id, e.metadata, e.visibility_tier,
                       e.linked_user_id, e.created_at, e.updated_at
                FROM entities e
                WHERE e.id = $1
                AND (
                    (e.owner_type = 'user' AND e.owner_id = $2)
                    OR (e.owner_type = 'family' AND e.owner_id = ANY($3::uuid[]))
                )
                """,
                UUID(entity_id),
                db_user_id,
                family_uuid_list,
            )

            if not entity:
                return {"status": "error", "message": "Entity not found or access denied"}

            # Get entity attributes
            attributes = await execute_query(
                """
                SELECT attribute_name, attribute_value, valid_from, valid_to
                FROM entity_attributes
                WHERE entity_id = $1
                AND (valid_to IS NULL OR valid_to > CURRENT_DATE)
                ORDER BY attribute_name
                """,
                UUID(entity_id),
            )

            # Get entity locations
            locations = await execute_query(
                """
                SELECT label, address_raw, ST_Y(location::geometry) as latitude,
                       ST_X(location::geometry) as longitude, valid_from, valid_to
                FROM entity_locations
                WHERE entity_id = $1
                AND (valid_to IS NULL OR valid_to > CURRENT_DATE)
                ORDER BY label
                """,
                UUID(entity_id),
            )

            # Get entity relationships
            relationships = await execute_query(
                """
                SELECT er.id, er.relationship_type,
                       CASE WHEN er.source_entity_id = $1 THEN er.target_entity_id ELSE er.source_entity_id END as related_id,
                       e.name as related_name, e.entity_type::text as related_type,
                       CASE WHEN er.source_entity_id = $1 THEN 'outgoing' ELSE 'incoming' END as direction
                FROM entity_relationships er
                JOIN entities e ON e.id = CASE WHEN er.source_entity_id = $1 THEN er.target_entity_id ELSE er.source_entity_id END
                WHERE (er.source_entity_id = $1 OR er.target_entity_id = $1)
                AND (er.valid_to IS NULL OR er.valid_to > CURRENT_DATE)
                ORDER BY e.name
                """,
                UUID(entity_id),
            )

            # Get recent facts about this entity
            facts = await execute_query(
                """
                SELECT f.id, f.content, f.importance, f.recorded_at, f.valid_from, f.valid_to
                FROM facts f
                WHERE f.about_entity_id = $1
                AND (f.valid_to IS NULL OR f.valid_to > CURRENT_DATE)
                ORDER BY f.importance DESC, f.recorded_at DESC
                LIMIT 10
                """,
                UUID(entity_id),
            )

            # Handle metadata safely
            metadata = entity["metadata"]
            if metadata is None:
                metadata_dict = {}
            elif isinstance(metadata, dict):
                metadata_dict = metadata
            elif hasattr(metadata, 'items'):
                metadata_dict = dict(metadata)
            else:
                metadata_dict = {}

            return {
                "status": "success",
                "entity": {
                    "id": str(entity["id"]),
                    "entity_type": entity["entity_type"],
                    "name": entity["name"],
                    "normalized_name": entity["normalized_name"],
                    "description": entity["description"],
                    "aliases": list(entity["aliases"]) if entity["aliases"] else [],
                    "metadata": metadata_dict,
                    "visibility_tier": entity["visibility_tier"],
                    "linked_user_id": str(entity["linked_user_id"]) if entity["linked_user_id"] else None,
                    "created_at": entity["created_at"].isoformat(),
                    "updated_at": entity["updated_at"].isoformat(),
                },
                "attributes": [
                    {
                        "name": attr["attribute_name"],
                        "value": attr["attribute_value"],
                        "valid_from": attr["valid_from"].isoformat() if attr["valid_from"] else None,
                        "valid_to": attr["valid_to"].isoformat() if attr["valid_to"] else None,
                    }
                    for attr in attributes
                ],
                "locations": [
                    {
                        "label": loc["label"],
                        "address": loc["address_raw"],
                        "latitude": float(loc["latitude"]) if loc["latitude"] else None,
                        "longitude": float(loc["longitude"]) if loc["longitude"] else None,
                    }
                    for loc in locations
                ],
                "relationships": [
                    {
                        "id": str(rel["id"]),
                        "relationship_type": rel["relationship_type"],
                        "related_entity_id": str(rel["related_id"]),
                        "related_entity_name": rel["related_name"],
                        "related_entity_type": rel["related_type"],
                        "direction": rel["direction"],
                    }
                    for rel in relationships
                ],
                "recent_facts": [
                    {
                        "id": str(f["id"]),
                        "content": f["content"],
                        "importance": f["importance"],
                        "recorded_at": f["recorded_at"].isoformat(),
                        "valid_from": f["valid_from"].isoformat() if f["valid_from"] else None,
                        "valid_to": f["valid_to"].isoformat() if f["valid_to"] else None,
                    }
                    for f in facts
                ],
            }
        except Exception as e:
            import traceback
            return {
                "status": "error",
                "message": f"Exception in entity_get_details: {str(e)}",
                "traceback": traceback.format_exc(),
            }

    try:
        result = run_async(_get_details())
        print(f"entity_get_details result: {result}")
        return result
    except Exception as e:
        import traceback
        error_result = {
            "status": "error",
            "message": f"Exception running entity_get_details: {str(e)}",
            "traceback": traceback.format_exc(),
        }
        print(f"entity_get_details error: {error_result}")
        return error_result


@tool
def entity_link_to_fact(
    fact_id: str,
    entity_id: str,
    role: str = "reference",
    confidence: float = 1.0,
) -> dict[str, Any]:
    """Link an entity mention to a fact.

    Use this tool to record that a fact mentions or is about a specific entity.
    This enables querying facts by entity.

    Args:
        fact_id: UUID of the fact.
        entity_id: UUID of the entity being mentioned.
        role: Role of the entity in the fact (subject, object, location, organization, reference).
        confidence: Confidence score 0-1 for the entity extraction.

    Returns:
        Dictionary with status of the link operation.
    """
    async def _link() -> dict[str, Any]:
        await execute_command(
            """
            INSERT INTO entity_mentions (fact_id, entity_id, role, confidence)
            VALUES ($1, $2, $3::mention_role, $4)
            ON CONFLICT (fact_id, entity_id, role) DO UPDATE SET
                confidence = EXCLUDED.confidence
            """,
            UUID(fact_id),
            UUID(entity_id),
            role,
            confidence,
        )

        return {
            "status": "success",
            "fact_id": fact_id,
            "entity_id": entity_id,
            "role": role,
        }

    return run_async(_link())
