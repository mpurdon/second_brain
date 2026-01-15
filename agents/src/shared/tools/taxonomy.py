"""Taxonomy tools for tag analysis and suggestions."""

import asyncio
from typing import Any
from uuid import UUID

from strands import tool

from ..database import execute_query


@tool
def tag_cooccurrence_analysis(
    user_id: str,
    family_ids: list[str] | None = None,
    min_cooccurrence: int = 3,
    limit: int = 20,
) -> dict[str, Any]:
    """Analyze which tags frequently appear together on the same facts.

    Use this tool to discover patterns in how users tag their information.
    High co-occurrence suggests related concepts or potential taxonomy improvements.

    Args:
        user_id: UUID of the user.
        family_ids: Optional list of family IDs.
        min_cooccurrence: Minimum times tags must appear together.
        limit: Maximum patterns to return.

    Returns:
        Dictionary with tag co-occurrence patterns.
    """
    async def _analyze() -> dict[str, Any]:
        family_uuid_list = [UUID(fid) for fid in (family_ids or [])]

        results = await execute_query(
            """
            WITH accessible_facts AS (
                SELECT f.id
                FROM facts f
                LEFT JOIN user_access_cache uac
                    ON f.owner_type = 'user'
                    AND f.owner_id = uac.target_user_id
                    AND uac.viewer_user_id = $1
                WHERE (
                    (f.owner_type = 'user' AND f.owner_id = $1)
                    OR (f.owner_type = 'user' AND uac.access_tier IS NOT NULL)
                    OR (f.owner_type = 'family' AND f.owner_id = ANY($2::uuid[]))
                )
            ),
            tag_pairs AS (
                SELECT
                    t1.path as tag1_path,
                    t1.name as tag1_name,
                    t2.path as tag2_path,
                    t2.name as tag2_name,
                    COUNT(*) as cooccurrence_count
                FROM fact_tags ft1
                JOIN fact_tags ft2 ON ft1.fact_id = ft2.fact_id AND ft1.tag_id < ft2.tag_id
                JOIN tags t1 ON t1.id = ft1.tag_id
                JOIN tags t2 ON t2.id = ft2.tag_id
                WHERE ft1.fact_id IN (SELECT id FROM accessible_facts)
                GROUP BY t1.path, t1.name, t2.path, t2.name
                HAVING COUNT(*) >= $3
            )
            SELECT * FROM tag_pairs
            ORDER BY cooccurrence_count DESC
            LIMIT $4
            """,
            UUID(user_id),
            family_uuid_list,
            min_cooccurrence,
            limit,
        )

        patterns = [
            {
                "tag1": {"path": row["tag1_path"], "name": row["tag1_name"]},
                "tag2": {"path": row["tag2_path"], "name": row["tag2_name"]},
                "cooccurrence_count": row["cooccurrence_count"],
            }
            for row in results
        ]

        return {
            "status": "success",
            "count": len(patterns),
            "patterns": patterns,
            "insight": _generate_cooccurrence_insight(patterns),
        }

    return asyncio.get_event_loop().run_until_complete(_analyze())


def _generate_cooccurrence_insight(patterns: list[dict]) -> str:
    """Generate human-readable insight from co-occurrence patterns."""
    if not patterns:
        return "No significant tag co-occurrence patterns found."

    insights = []
    for p in patterns[:3]:
        insights.append(
            f"'{p['tag1']['name']}' and '{p['tag2']['name']}' "
            f"appear together {p['cooccurrence_count']} times"
        )

    return "; ".join(insights)


@tool
def untagged_facts_analysis(
    user_id: str,
    family_ids: list[str] | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Find facts that have no tags applied.

    Use this tool to identify gaps in the taxonomy where facts are missing
    categorization. These are candidates for automatic tag suggestions.

    Args:
        user_id: UUID of the user.
        family_ids: Optional list of family IDs.
        limit: Maximum untagged facts to return.

    Returns:
        Dictionary with untagged facts and statistics.
    """
    async def _analyze() -> dict[str, Any]:
        family_uuid_list = [UUID(fid) for fid in (family_ids or [])]

        # Get untagged facts
        untagged = await execute_query(
            """
            SELECT f.id, f.content, f.importance, f.recorded_at,
                   e.name as entity_name, e.entity_type
            FROM facts f
            LEFT JOIN entities e ON e.id = f.about_entity_id
            LEFT JOIN user_access_cache uac
                ON f.owner_type = 'user'
                AND f.owner_id = uac.target_user_id
                AND uac.viewer_user_id = $1
            WHERE (
                (f.owner_type = 'user' AND f.owner_id = $1)
                OR (f.owner_type = 'user' AND uac.access_tier IS NOT NULL)
                OR (f.owner_type = 'family' AND f.owner_id = ANY($2::uuid[]))
            )
            AND NOT EXISTS (
                SELECT 1 FROM fact_tags ft WHERE ft.fact_id = f.id
            )
            ORDER BY f.importance DESC, f.recorded_at DESC
            LIMIT $3
            """,
            UUID(user_id),
            family_uuid_list,
            limit,
        )

        # Get total counts for statistics
        stats = await execute_query(
            """
            WITH accessible_facts AS (
                SELECT f.id
                FROM facts f
                LEFT JOIN user_access_cache uac
                    ON f.owner_type = 'user'
                    AND f.owner_id = uac.target_user_id
                    AND uac.viewer_user_id = $1
                WHERE (
                    (f.owner_type = 'user' AND f.owner_id = $1)
                    OR (f.owner_type = 'user' AND uac.access_tier IS NOT NULL)
                    OR (f.owner_type = 'family' AND f.owner_id = ANY($2::uuid[]))
                )
            )
            SELECT
                COUNT(*) as total_facts,
                COUNT(*) FILTER (WHERE id NOT IN (SELECT fact_id FROM fact_tags)) as untagged_facts
            FROM accessible_facts
            """,
            UUID(user_id),
            family_uuid_list,
        )

        total = stats[0]["total_facts"] if stats else 0
        untagged_count = stats[0]["untagged_facts"] if stats else 0
        coverage = ((total - untagged_count) / total * 100) if total > 0 else 0

        facts = [
            {
                "id": str(row["id"]),
                "content": row["content"][:200],  # Truncate for analysis
                "importance": row["importance"],
                "recorded_at": row["recorded_at"].isoformat(),
                "entity_name": row["entity_name"],
                "entity_type": row["entity_type"],
            }
            for row in untagged
        ]

        return {
            "status": "success",
            "statistics": {
                "total_facts": total,
                "untagged_facts": untagged_count,
                "tag_coverage_percent": round(coverage, 1),
            },
            "untagged_facts": facts,
        }

    return asyncio.get_event_loop().run_until_complete(_analyze())


@tool
def tag_hierarchy_analysis(
    user_id: str,
    family_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Analyze the current tag hierarchy structure.

    Use this tool to understand the taxonomy organization and identify:
    - Deeply nested paths that might need simplification
    - Sparse branches with few facts
    - Dense branches that might need subdivision

    Args:
        user_id: UUID of the user.
        family_ids: Optional list of family IDs.

    Returns:
        Dictionary with hierarchy analysis.
    """
    async def _analyze() -> dict[str, Any]:
        family_uuid_list = [UUID(fid) for fid in (family_ids or [])]

        # Analyze tag usage by path prefix
        results = await execute_query(
            """
            WITH accessible_facts AS (
                SELECT f.id
                FROM facts f
                LEFT JOIN user_access_cache uac
                    ON f.owner_type = 'user'
                    AND f.owner_id = uac.target_user_id
                    AND uac.viewer_user_id = $1
                WHERE (
                    (f.owner_type = 'user' AND f.owner_id = $1)
                    OR (f.owner_type = 'user' AND uac.access_tier IS NOT NULL)
                    OR (f.owner_type = 'family' AND f.owner_id = ANY($2::uuid[]))
                )
            ),
            tag_stats AS (
                SELECT
                    t.path,
                    t.name,
                    ARRAY_LENGTH(STRING_TO_ARRAY(t.path, '/'), 1) as depth,
                    COUNT(DISTINCT ft.fact_id) as fact_count,
                    SPLIT_PART(t.path, '/', 1) as root_category
                FROM tags t
                LEFT JOIN fact_tags ft ON ft.tag_id = t.id
                    AND ft.fact_id IN (SELECT id FROM accessible_facts)
                WHERE t.owner_type IS NULL
                   OR (t.owner_type = 'user' AND t.owner_id = $1)
                   OR (t.owner_type = 'family' AND t.owner_id = ANY($2::uuid[]))
                GROUP BY t.id
            )
            SELECT
                root_category,
                COUNT(*) as tag_count,
                SUM(fact_count) as total_facts,
                MAX(depth) as max_depth,
                AVG(depth)::numeric(3,1) as avg_depth,
                ARRAY_AGG(path ORDER BY fact_count DESC) FILTER (WHERE fact_count > 0) as popular_paths
            FROM tag_stats
            GROUP BY root_category
            ORDER BY total_facts DESC
            """,
            UUID(user_id),
            family_uuid_list,
        )

        categories = [
            {
                "category": row["root_category"],
                "tag_count": row["tag_count"],
                "total_facts": row["total_facts"] or 0,
                "max_depth": row["max_depth"],
                "avg_depth": float(row["avg_depth"]) if row["avg_depth"] else 0,
                "popular_paths": (row["popular_paths"] or [])[:5],
            }
            for row in results
        ]

        # Identify potential issues
        issues = []
        for cat in categories:
            if cat["max_depth"] > 4:
                issues.append(f"'{cat['category']}' has deep nesting (depth {cat['max_depth']})")
            if cat["tag_count"] > 20 and cat["total_facts"] < cat["tag_count"]:
                issues.append(f"'{cat['category']}' has many unused tags")
            if cat["total_facts"] > 100 and cat["tag_count"] < 3:
                issues.append(f"'{cat['category']}' might need more subdivisions")

        return {
            "status": "success",
            "categories": categories,
            "issues": issues,
            "total_categories": len(categories),
        }

    return asyncio.get_event_loop().run_until_complete(_analyze())


@tool
def suggest_tags_for_fact(
    fact_id: str,
    user_id: str,
    family_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Suggest tags for a specific fact based on content and patterns.

    Use this tool to get tag recommendations for a fact based on:
    - Similar facts and their tags
    - Entity type associations
    - Content keyword matching

    Args:
        fact_id: UUID of the fact to get suggestions for.
        user_id: UUID of the user.
        family_ids: Optional list of family IDs.

    Returns:
        Dictionary with tag suggestions and confidence scores.
    """
    async def _suggest() -> dict[str, Any]:
        family_uuid_list = [UUID(fid) for fid in (family_ids or [])]

        # Get the fact content and entity info
        fact = await execute_query(
            """
            SELECT f.content, f.about_entity_id, e.entity_type, e.name as entity_name
            FROM facts f
            LEFT JOIN entities e ON e.id = f.about_entity_id
            WHERE f.id = $1
            """,
            UUID(fact_id),
        )

        if not fact:
            return {"status": "error", "message": "Fact not found"}

        fact_content = fact[0]["content"]
        entity_type = fact[0]["entity_type"]

        suggestions = []

        # Suggest based on entity type
        if entity_type:
            entity_tags = await execute_query(
                """
                SELECT t.path, t.name, COUNT(*) as usage_count
                FROM tags t
                JOIN fact_tags ft ON ft.tag_id = t.id
                JOIN facts f ON f.id = ft.fact_id
                JOIN entities e ON e.id = f.about_entity_id
                WHERE e.entity_type = $1
                AND (t.owner_type IS NULL OR t.owner_type = 'user' AND t.owner_id = $2)
                GROUP BY t.id
                ORDER BY usage_count DESC
                LIMIT 5
                """,
                entity_type,
                UUID(user_id),
            )
            for row in entity_tags:
                suggestions.append({
                    "path": row["path"],
                    "name": row["name"],
                    "reason": f"commonly used with {entity_type} entities",
                    "confidence": min(0.9, 0.5 + (row["usage_count"] / 20)),
                })

        # Suggest based on content keywords (simple matching)
        keyword_tags = await execute_query(
            """
            SELECT t.path, t.name,
                   CASE
                       WHEN $1 ILIKE '%' || t.name || '%' THEN 0.8
                       WHEN $1 ILIKE '%' || SPLIT_PART(t.path, '/', 1) || '%' THEN 0.6
                       ELSE 0.4
                   END as confidence
            FROM tags t
            WHERE (t.owner_type IS NULL OR t.owner_type = 'user' AND t.owner_id = $2)
            AND ($1 ILIKE '%' || t.name || '%' OR $1 ILIKE '%' || SPLIT_PART(t.path, '/', 1) || '%')
            ORDER BY confidence DESC
            LIMIT 5
            """,
            fact_content,
            UUID(user_id),
        )
        for row in keyword_tags:
            if not any(s["path"] == row["path"] for s in suggestions):
                suggestions.append({
                    "path": row["path"],
                    "name": row["name"],
                    "reason": "keyword match in content",
                    "confidence": float(row["confidence"]),
                })

        # Sort by confidence
        suggestions.sort(key=lambda x: x["confidence"], reverse=True)

        return {
            "status": "success",
            "fact_id": fact_id,
            "suggestions": suggestions[:10],
        }

    return asyncio.get_event_loop().run_until_complete(_suggest())


@tool
def propose_taxonomy_changes(
    user_id: str,
    family_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Propose taxonomy improvements based on usage patterns.

    Use this tool to generate actionable proposals for improving the tag taxonomy:
    - Merge frequently co-occurring tags
    - Create parent tags for orphaned tags
    - Suggest new tags for common content patterns

    Args:
        user_id: UUID of the user.
        family_ids: Optional list of family IDs.

    Returns:
        Dictionary with taxonomy improvement proposals.
    """
    async def _propose() -> dict[str, Any]:
        family_uuid_list = [UUID(fid) for fid in (family_ids or [])]

        proposals = []

        # Find tags that could be merged (very high co-occurrence)
        merge_candidates = await execute_query(
            """
            WITH tag_pairs AS (
                SELECT
                    t1.id as tag1_id, t1.path as tag1_path, t1.name as tag1_name,
                    t2.id as tag2_id, t2.path as tag2_path, t2.name as tag2_name,
                    COUNT(*) as together_count,
                    (SELECT COUNT(*) FROM fact_tags WHERE tag_id = t1.id) as tag1_total,
                    (SELECT COUNT(*) FROM fact_tags WHERE tag_id = t2.id) as tag2_total
                FROM fact_tags ft1
                JOIN fact_tags ft2 ON ft1.fact_id = ft2.fact_id AND ft1.tag_id < ft2.tag_id
                JOIN tags t1 ON t1.id = ft1.tag_id
                JOIN tags t2 ON t2.id = ft2.tag_id
                WHERE t1.is_system = false AND t2.is_system = false
                GROUP BY t1.id, t1.path, t1.name, t2.id, t2.path, t2.name
            )
            SELECT * FROM tag_pairs
            WHERE together_count::float / LEAST(tag1_total, tag2_total) > 0.8
            AND together_count >= 5
            ORDER BY together_count DESC
            LIMIT 5
            """,
        )

        for row in merge_candidates:
            proposals.append({
                "type": "merge",
                "action": f"Consider merging '{row['tag1_name']}' and '{row['tag2_name']}'",
                "reason": f"They appear together {row['together_count']} times "
                          f"({int(row['together_count'] / min(row['tag1_total'], row['tag2_total']) * 100)}% overlap)",
                "tags": [row["tag1_path"], row["tag2_path"]],
            })

        # Find orphan tags (no parent in hierarchy)
        orphan_tags = await execute_query(
            """
            SELECT path, name
            FROM tags
            WHERE path NOT LIKE '%/%'
            AND is_system = false
            AND (owner_type IS NULL OR owner_type = 'user' AND owner_id = $1)
            AND id IN (SELECT tag_id FROM fact_tags)
            ORDER BY name
            LIMIT 10
            """,
            UUID(user_id),
        )

        if len(orphan_tags) > 3:
            proposals.append({
                "type": "organize",
                "action": "Consider creating category prefixes for top-level tags",
                "reason": f"Found {len(orphan_tags)} top-level tags without hierarchy",
                "tags": [row["path"] for row in orphan_tags],
            })

        # Find underutilized tags
        underutilized = await execute_query(
            """
            SELECT t.path, t.name, COUNT(ft.fact_id) as usage_count
            FROM tags t
            LEFT JOIN fact_tags ft ON ft.tag_id = t.id
            WHERE t.is_system = false
            AND (t.owner_type IS NULL OR t.owner_type = 'user' AND t.owner_id = $1)
            GROUP BY t.id
            HAVING COUNT(ft.fact_id) <= 1
            ORDER BY t.created_at
            LIMIT 10
            """,
            UUID(user_id),
        )

        if underutilized:
            proposals.append({
                "type": "cleanup",
                "action": "Review underutilized tags for removal",
                "reason": f"Found {len(underutilized)} tags with 0-1 uses",
                "tags": [row["path"] for row in underutilized],
            })

        return {
            "status": "success",
            "proposals": proposals,
            "total_proposals": len(proposals),
        }

    return asyncio.get_event_loop().run_until_complete(_propose())
