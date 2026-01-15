"""Vector search tools using pgvector and Amazon Bedrock."""

import asyncio
import json
from typing import Any
from uuid import UUID

import boto3
from strands import tool

from ..config import get_settings
from ..database import execute_one, execute_query


def _get_bedrock_client():
    """Get Bedrock runtime client."""
    settings = get_settings()
    return boto3.client("bedrock-runtime", region_name=settings.aws_region)


@tool
def generate_embedding(text: str) -> dict[str, Any]:
    """Generate a vector embedding for the given text.

    Use this tool to create embeddings for semantic search or similarity comparison.
    Uses Amazon Titan Embeddings V2 model.

    Args:
        text: The text to generate an embedding for.

    Returns:
        Dictionary with the embedding vector and dimensions.
    """
    settings = get_settings()
    client = _get_bedrock_client()

    response = client.invoke_model(
        modelId=settings.embedding_model_id,
        body=json.dumps({
            "inputText": text,
            "dimensions": settings.embedding_dimensions,
            "normalize": True,
        }),
    )

    result = json.loads(response["body"].read())
    embedding = result["embedding"]

    return {
        "status": "success",
        "embedding": embedding,
        "dimensions": len(embedding),
    }


@tool
def semantic_search(
    user_id: str,
    query: str,
    family_ids: list[str] | None = None,
    limit: int = 10,
    similarity_threshold: float = 0.7,
) -> dict[str, Any]:
    """Search for facts using semantic similarity with permission filtering.

    Use this tool when you need to find facts related to a concept or topic,
    even if the exact words don't match. Results are ranked by semantic similarity.
    Automatically filters results based on the user's access permissions.

    Args:
        user_id: UUID of the user performing the search.
        query: Natural language query to search for.
        family_ids: Optional list of family UUIDs to include in search scope.
        limit: Maximum number of results to return (default 10).
        similarity_threshold: Minimum similarity score 0-1 (default 0.7).

    Returns:
        Dictionary with matching facts ranked by similarity.
    """
    async def _search() -> dict[str, Any]:
        # Generate embedding for the query
        embedding_result = generate_embedding(query)
        if embedding_result["status"] != "success":
            return {"status": "error", "message": "Failed to generate query embedding"}

        query_embedding = embedding_result["embedding"]

        # Build family IDs array for query
        family_uuid_list = [UUID(fid) for fid in (family_ids or [])]

        # Permission-aware search using pgvector cosine similarity
        # This query handles:
        # 1. User's own facts (always visible)
        # 2. Facts from users the viewer has relationships with (filtered by visibility_tier)
        # 3. Family-owned facts (visible to all family members)
        search_query = """
            WITH query_embedding AS (
                SELECT $1::vector AS vec
            )
            SELECT
                f.id,
                f.content,
                f.importance,
                f.visibility_tier,
                f.recorded_at,
                f.owner_type,
                f.owner_id,
                e.name as entity_name,
                1 - (fe.embedding <=> qe.vec) as similarity
            FROM facts f
            JOIN fact_embeddings fe ON fe.fact_id = f.id
            CROSS JOIN query_embedding qe
            LEFT JOIN entities e ON e.id = f.about_entity_id
            LEFT JOIN user_access_cache uac
                ON f.owner_type = 'user'
                AND f.owner_id = uac.target_user_id
                AND uac.viewer_user_id = $2
            WHERE (
                -- User's own facts
                (f.owner_type = 'user' AND f.owner_id = $2)
                -- Facts from related users (with permission check)
                OR (f.owner_type = 'user' AND uac.access_tier IS NOT NULL AND uac.access_tier <= f.visibility_tier)
                -- Family-owned facts (if user is in that family)
                OR (f.owner_type = 'family' AND f.owner_id = ANY($3::uuid[]))
            )
            AND (f.valid_to IS NULL OR f.valid_to > CURRENT_DATE)
            AND 1 - (fe.embedding <=> qe.vec) >= $4
            ORDER BY similarity DESC
            LIMIT $5
        """

        # Convert embedding list to PostgreSQL vector format
        embedding_str = "[" + ",".join(str(x) for x in query_embedding) + "]"

        results = await execute_query(
            search_query,
            embedding_str,
            UUID(user_id),
            family_uuid_list,
            similarity_threshold,
            limit,
        )

        facts = [
            {
                "id": str(row["id"]),
                "content": row["content"],
                "importance": row["importance"],
                "visibility_tier": row["visibility_tier"],
                "similarity": float(row["similarity"]),
                "recorded_at": row["recorded_at"].isoformat(),
                "entity_name": row["entity_name"],
                "owner_type": row["owner_type"],
            }
            for row in results
        ]

        return {
            "status": "success",
            "query": query,
            "count": len(facts),
            "results": facts,
        }

    return asyncio.get_event_loop().run_until_complete(_search())


@tool
def store_fact_embedding(fact_id: str, content: str) -> dict[str, Any]:
    """Generate and store an embedding for a fact.

    This tool is used internally after storing a new fact to enable
    semantic search. It generates an embedding and stores it in the
    fact_embeddings table.

    Args:
        fact_id: UUID of the fact to generate embedding for.
        content: The fact content to embed.

    Returns:
        Dictionary with status and embedding info.
    """
    async def _store() -> dict[str, Any]:
        # Generate embedding
        embedding_result = generate_embedding(content)
        if embedding_result["status"] != "success":
            return {"status": "error", "message": "Failed to generate embedding"}

        embedding = embedding_result["embedding"]
        settings = get_settings()

        # Store embedding
        embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"

        await execute_one(
            """
            INSERT INTO fact_embeddings (fact_id, embedding, model_id)
            VALUES ($1, $2::vector, $3)
            ON CONFLICT (fact_id) DO UPDATE SET
                embedding = EXCLUDED.embedding,
                model_id = EXCLUDED.model_id,
                created_at = NOW()
            RETURNING fact_id
            """,
            UUID(fact_id),
            embedding_str,
            settings.embedding_model_id,
        )

        return {
            "status": "success",
            "fact_id": fact_id,
            "dimensions": len(embedding),
            "model_id": settings.embedding_model_id,
        }

    return asyncio.get_event_loop().run_until_complete(_store())
