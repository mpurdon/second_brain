-- Query Optimization Migration
-- Adds indexes and optimizations for common query patterns

-- ===========================================
-- FACTS TABLE OPTIMIZATIONS
-- ===========================================

-- Composite index for permission-aware fact queries (most common pattern)
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_facts_owner_visibility
ON facts(owner_type, owner_id, visibility_tier);

-- Index for temporal queries (valid_from/valid_to filtering)
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_facts_temporal
ON facts(valid_from, valid_to) WHERE valid_from IS NOT NULL OR valid_to IS NOT NULL;

-- Index for importance-based sorting
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_facts_importance_recorded
ON facts(importance DESC, recorded_at DESC);

-- Full-text search on fact content
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_facts_content_trgm
ON facts USING gin(content gin_trgm_ops);

-- ===========================================
-- ENTITIES TABLE OPTIMIZATIONS
-- ===========================================

-- Composite index for entity searches
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_entities_owner_type
ON entities(owner_type, owner_id, entity_type);

-- Trigram index for fuzzy name matching
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_entities_name_trgm
ON entities USING gin(name gin_trgm_ops);

-- Normalized name for exact lookups
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_entities_normalized
ON entities(normalized_name);

-- ===========================================
-- TAGS TABLE OPTIMIZATIONS
-- ===========================================

-- Path prefix search (for autocomplete and hierarchy)
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_tags_path_prefix
ON tags USING btree(path text_pattern_ops);

-- Owner-based tag filtering
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_tags_owner
ON tags(owner_type, owner_id) WHERE owner_type IS NOT NULL;

-- ===========================================
-- FACT_TAGS TABLE OPTIMIZATIONS
-- ===========================================

-- Reverse lookup: tags -> facts
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_fact_tags_tag
ON fact_tags(tag_id);

-- ===========================================
-- USER_ACCESS_CACHE OPTIMIZATIONS
-- ===========================================

-- Viewer-based access lookup
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_uac_viewer_access
ON user_access_cache(viewer_user_id, access_tier);

-- Target-based lookup for permission checks
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_uac_target
ON user_access_cache(target_user_id);

-- ===========================================
-- ENTITY_LOCATIONS OPTIMIZATIONS
-- ===========================================

-- Spatial index for proximity queries (if not exists)
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_entity_locations_geo
ON entity_locations USING gist(location);

-- Entity location lookup
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_entity_locations_entity
ON entity_locations(entity_id);

-- ===========================================
-- EMBEDDINGS OPTIMIZATIONS
-- ===========================================

-- HNSW index for faster vector similarity (if using pgvector)
-- Note: This is more memory-intensive but faster for queries
-- DROP INDEX IF EXISTS idx_embeddings_vector;
-- CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_embeddings_vector_hnsw
-- ON embeddings USING hnsw(embedding vector_cosine_ops);

-- Source reference lookup
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_embeddings_source
ON embeddings(source_type, source_id);

-- ===========================================
-- QUERY PERFORMANCE FUNCTIONS
-- ===========================================

-- Optimized function for getting accessible fact IDs
CREATE OR REPLACE FUNCTION get_accessible_fact_ids(
    p_viewer_id UUID,
    p_family_ids UUID[],
    p_limit INTEGER DEFAULT 1000
)
RETURNS TABLE(fact_id UUID) AS $$
BEGIN
    RETURN QUERY
    SELECT f.id
    FROM facts f
    LEFT JOIN user_access_cache uac
        ON f.owner_type = 'user'
        AND f.owner_id = uac.target_user_id
        AND uac.viewer_user_id = p_viewer_id
    WHERE (
        -- User's own facts
        (f.owner_type = 'user' AND f.owner_id = p_viewer_id)
        -- Related user facts with permission
        OR (f.owner_type = 'user' AND uac.access_tier IS NOT NULL AND uac.access_tier <= f.visibility_tier)
        -- Family facts
        OR (f.owner_type = 'family' AND f.owner_id = ANY(p_family_ids))
    )
    LIMIT p_limit;
END;
$$ LANGUAGE plpgsql STABLE;

-- ===========================================
-- ANALYZE UPDATED TABLES
-- ===========================================

ANALYZE facts;
ANALYZE entities;
ANALYZE tags;
ANALYZE fact_tags;
ANALYZE user_access_cache;
ANALYZE entity_locations;
ANALYZE embeddings;

COMMENT ON INDEX idx_facts_owner_visibility IS 'Optimizes permission-aware fact queries';
COMMENT ON INDEX idx_facts_content_trgm IS 'Enables fast text search on fact content';
COMMENT ON INDEX idx_entities_name_trgm IS 'Enables fuzzy matching on entity names';
COMMENT ON INDEX idx_tags_path_prefix IS 'Enables fast prefix matching for tag autocomplete';
