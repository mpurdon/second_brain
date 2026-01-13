-- Migration: 009_functions
-- Description: Create functions and triggers for access cache
-- Date: 2025-01

-- Function to rebuild access cache for a specific user
CREATE OR REPLACE FUNCTION refresh_user_access_cache(p_user_id UUID)
RETURNS VOID AS $$
BEGIN
    -- Delete existing cache for this user
    DELETE FROM user_access_cache WHERE viewer_user_id = p_user_id;

    -- Rebuild using recursive CTE
    INSERT INTO user_access_cache (viewer_user_id, target_user_id, access_tier, relationship_path, hop_count)
    WITH RECURSIVE accessible_users AS (
        -- Base case: direct relationships
        SELECT
            r.source_user_id AS viewer_user_id,
            r.target_user_id,
            r.access_tier,
            ARRAY[r.id] AS relationship_path,
            1 AS hop_count
        FROM relationships r
        WHERE r.source_user_id = p_user_id
          AND (r.valid_to IS NULL OR r.valid_to > CURRENT_DATE)
          AND (r.valid_from IS NULL OR r.valid_from <= CURRENT_DATE)

        UNION ALL

        -- Recursive case: follow relationships (max 4 hops)
        SELECT
            au.viewer_user_id,
            r.target_user_id,
            GREATEST(au.access_tier, r.access_tier) AS access_tier,
            au.relationship_path || r.id,
            au.hop_count + 1
        FROM accessible_users au
        JOIN relationships r ON r.source_user_id = au.target_user_id
        WHERE au.hop_count < 4
          AND NOT (r.target_user_id = ANY(
              SELECT target_user_id FROM accessible_users WHERE viewer_user_id = au.viewer_user_id
          ))
          AND (r.valid_to IS NULL OR r.valid_to > CURRENT_DATE)
          AND (r.valid_from IS NULL OR r.valid_from <= CURRENT_DATE)
    )
    SELECT DISTINCT ON (viewer_user_id, target_user_id)
        viewer_user_id,
        target_user_id,
        access_tier,
        relationship_path,
        hop_count
    FROM accessible_users
    ORDER BY viewer_user_id, target_user_id, access_tier ASC, hop_count ASC;
END;
$$ LANGUAGE plpgsql;

-- Trigger function to refresh cache when relationships change
CREATE OR REPLACE FUNCTION trigger_refresh_access_cache()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        PERFORM refresh_user_access_cache(OLD.source_user_id);
        IF OLD.bidirectional THEN
            PERFORM refresh_user_access_cache(OLD.target_user_id);
        END IF;
    ELSE
        PERFORM refresh_user_access_cache(NEW.source_user_id);
        IF NEW.bidirectional THEN
            PERFORM refresh_user_access_cache(NEW.target_user_id);
        END IF;
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

-- Create trigger on relationships table
CREATE TRIGGER relationships_cache_refresh
AFTER INSERT OR UPDATE OR DELETE ON relationships
FOR EACH ROW EXECUTE FUNCTION trigger_refresh_access_cache();

-- Function to get visible facts for a user
CREATE OR REPLACE FUNCTION get_visible_facts(
    p_user_id UUID,
    p_family_ids UUID[],
    p_limit INT DEFAULT 100
)
RETURNS TABLE (
    fact_id UUID,
    content TEXT,
    importance SMALLINT,
    visibility_tier SMALLINT,
    recorded_at TIMESTAMPTZ,
    entity_name VARCHAR
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        f.id AS fact_id,
        f.content,
        f.importance,
        f.visibility_tier,
        f.recorded_at,
        e.name AS entity_name
    FROM facts f
    LEFT JOIN entities e ON e.id = f.about_entity_id
    LEFT JOIN user_access_cache uac
        ON f.owner_type = 'user'
        AND f.owner_id = uac.target_user_id
        AND uac.viewer_user_id = p_user_id
    WHERE
        (
            -- User owns the fact
            (f.owner_type = 'user' AND f.owner_id = p_user_id)
            -- Or family owns it and user is in family
            OR (f.owner_type = 'family' AND f.owner_id = ANY(p_family_ids))
            -- Or user has access via relationship graph
            OR (f.owner_type = 'user' AND uac.access_tier <= f.visibility_tier)
        )
        AND (f.valid_to IS NULL OR f.valid_to > CURRENT_DATE)
    ORDER BY f.importance DESC, f.recorded_at DESC
    LIMIT p_limit;
END;
$$ LANGUAGE plpgsql;
