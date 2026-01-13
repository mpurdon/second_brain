"""Entity management tools for Second Brain agents."""

import asyncio
from typing import Any
from uuid import UUID

from strands import tool

from ..database import execute_command, execute_one, execute_query


@tool
def entity_search(
    user_id: str,
    query: str | None = None,
    entity_type: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Search for entities in the knowledge base.

    Use this tool to find people, organizations, places, projects, or events.
    Supports fuzzy matching on names.

    Args:
        user_id: UUID of the user performing the search.
        query: Optional text to search for in entity names.
        entity_type: Optional filter by type (person, organization, place, project, event).
        limit: Maximum number of results to return (default 20).

    Returns:
        Dictionary with list of matching entities.
    """
    async def _search() -> dict[str, Any]:
        conditions = []
        params: list[Any] = [UUID(user_id)]
        param_idx = 2

        # Base query with ownership check
        base_query = """
            SELECT e.id, e.entity_type, e.name, e.canonical_name,
                   e.attributes, e.created_at,
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
            conditions.append(f"e.name ILIKE ${param_idx} OR e.canonical_name ILIKE ${param_idx}")
            params.append(f"%{query}%")
            param_idx += 1

        if entity_type:
            conditions.append(f"e.entity_type = ${param_idx}")
            params.append(entity_type)
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

        entities = [
            {
                "id": str(row["id"]),
                "entity_type": row["entity_type"],
                "name": row["name"],
                "canonical_name": row["canonical_name"],
                "attributes": dict(row["attributes"]) if row["attributes"] else {},
                "fact_count": row["fact_count"],
                "created_at": row["created_at"].isoformat(),
            }
            for row in results
        ]

        return {
            "status": "success",
            "count": len(entities),
            "entities": entities,
        }

    return asyncio.get_event_loop().run_until_complete(_search())


@tool
def entity_create(
    name: str,
    entity_type: str,
    owner_id: str,
    owner_type: str = "user",
    canonical_name: str | None = None,
    attributes: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a new entity in the knowledge base.

    Use this tool to create a new person, organization, place, project, or event.
    Entities are used to organize facts and relationships.

    Args:
        name: Display name for the entity (required).
        entity_type: Type of entity (person, organization, place, project, event).
        owner_id: UUID of the user or family that owns this entity.
        owner_type: Either 'user' or 'family'.
        canonical_name: Optional normalized name for matching (lowercase, no spaces).
        attributes: Optional dictionary of additional attributes.

    Returns:
        Dictionary with the created entity ID and details.
    """
    async def _create() -> dict[str, Any]:
        # Generate canonical name if not provided
        if canonical_name is None:
            computed_canonical = name.lower().replace(" ", "_")
        else:
            computed_canonical = canonical_name

        import json
        attrs_json = json.dumps(attributes or {})

        result = await execute_one(
            """
            INSERT INTO entities (entity_type, name, canonical_name, owner_type, owner_id, attributes)
            VALUES ($1, $2, $3, $4, $5, $6::jsonb)
            RETURNING id, created_at
            """,
            entity_type,
            name,
            computed_canonical,
            owner_type,
            UUID(owner_id),
            attrs_json,
        )

        if not result:
            return {"status": "error", "message": "Failed to create entity"}

        return {
            "status": "success",
            "entity_id": str(result["id"]),
            "name": name,
            "entity_type": entity_type,
            "canonical_name": computed_canonical,
            "created_at": result["created_at"].isoformat(),
        }

    return asyncio.get_event_loop().run_until_complete(_create())


@tool
def entity_get_details(
    user_id: str,
    entity_id: str,
) -> dict[str, Any]:
    """Get detailed information about an entity.

    Use this tool to retrieve complete information about an entity,
    including all its attributes, locations, and recent facts.

    Args:
        user_id: UUID of the user requesting the information.
        entity_id: UUID of the entity to retrieve.

    Returns:
        Dictionary with entity details, locations, and related facts.
    """
    async def _get_details() -> dict[str, Any]:
        # Get entity details
        entity = await execute_one(
            """
            SELECT e.id, e.entity_type, e.name, e.canonical_name,
                   e.owner_type, e.owner_id, e.attributes, e.created_at
            FROM entities e
            WHERE e.id = $1
            AND (
                (e.owner_type = 'user' AND e.owner_id = $2)
                OR e.owner_type = 'family'
            )
            """,
            UUID(entity_id),
            UUID(user_id),
        )

        if not entity:
            return {"status": "error", "message": "Entity not found or access denied"}

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

        # Get recent facts about this entity
        facts = await execute_query(
            """
            SELECT f.id, f.content, f.importance, f.recorded_at
            FROM facts f
            WHERE f.about_entity_id = $1
            AND (f.valid_to IS NULL OR f.valid_to > CURRENT_DATE)
            ORDER BY f.importance DESC, f.recorded_at DESC
            LIMIT 10
            """,
            UUID(entity_id),
        )

        # Get related entities (via entity_relationships if we had that table)
        # For now, just return the entity info

        return {
            "status": "success",
            "entity": {
                "id": str(entity["id"]),
                "entity_type": entity["entity_type"],
                "name": entity["name"],
                "canonical_name": entity["canonical_name"],
                "attributes": dict(entity["attributes"]) if entity["attributes"] else {},
                "created_at": entity["created_at"].isoformat(),
            },
            "locations": [
                {
                    "label": loc["label"],
                    "address": loc["address_raw"],
                    "latitude": float(loc["latitude"]) if loc["latitude"] else None,
                    "longitude": float(loc["longitude"]) if loc["longitude"] else None,
                }
                for loc in locations
            ],
            "recent_facts": [
                {
                    "id": str(f["id"]),
                    "content": f["content"],
                    "importance": f["importance"],
                    "recorded_at": f["recorded_at"].isoformat(),
                }
                for f in facts
            ],
        }

    return asyncio.get_event_loop().run_until_complete(_get_details())


@tool
def entity_link_to_fact(
    fact_id: str,
    entity_id: str,
    mention_type: str = "about",
    confidence: float = 1.0,
) -> dict[str, Any]:
    """Link an entity mention to a fact.

    Use this tool to record that a fact mentions or is about a specific entity.
    This enables querying facts by entity.

    Args:
        fact_id: UUID of the fact.
        entity_id: UUID of the entity being mentioned.
        mention_type: Type of mention (about, mentions, related_to).
        confidence: Confidence score 0-1 for the entity extraction.

    Returns:
        Dictionary with status of the link operation.
    """
    async def _link() -> dict[str, Any]:
        await execute_command(
            """
            INSERT INTO entity_mentions (fact_id, entity_id, mention_type, confidence)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (fact_id, entity_id) DO UPDATE SET
                mention_type = EXCLUDED.mention_type,
                confidence = EXCLUDED.confidence
            """,
            UUID(fact_id),
            UUID(entity_id),
            mention_type,
            confidence,
        )

        return {
            "status": "success",
            "fact_id": fact_id,
            "entity_id": entity_id,
            "mention_type": mention_type,
        }

    return asyncio.get_event_loop().run_until_complete(_link())
