-- Migration: 003_relationships
-- Description: Create relationship graph tables
-- Date: 2025-01

-- Relationship type enum
CREATE TYPE relationship_type AS ENUM (
    'spouse',
    'parent_of',
    'child_of',
    'grandparent_of',
    'grandchild_of',
    'sibling',
    'aunt_uncle_of',
    'niece_nephew_of',
    'cousin',
    'friend',
    'colleague',
    'custom'
);

-- Relationships table (user-to-user with access tiers)
CREATE TABLE relationships (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    target_user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    relationship_type relationship_type NOT NULL,
    custom_type_name VARCHAR(100),
    access_tier SMALLINT NOT NULL DEFAULT 3 CHECK (access_tier BETWEEN 1 AND 4),

    bidirectional BOOLEAN NOT NULL DEFAULT false,
    inverse_relationship_id UUID REFERENCES relationships(id),

    -- Temporal validity
    valid_from DATE,
    valid_to DATE,
    valid_range TSTZRANGE GENERATED ALWAYS AS (
        TSTZRANGE(
            COALESCE(valid_from, '-infinity')::TIMESTAMPTZ,
            COALESCE(valid_to, 'infinity')::TIMESTAMPTZ,
            '[)'
        )
    ) STORED,

    metadata JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by UUID REFERENCES users(id),

    CONSTRAINT relationships_no_self CHECK (source_user_id != target_user_id),
    CONSTRAINT relationships_custom_requires_name CHECK (
        relationship_type != 'custom' OR custom_type_name IS NOT NULL
    )
);

CREATE UNIQUE INDEX idx_relationships_unique_active ON relationships(
    source_user_id, target_user_id, relationship_type
) WHERE valid_to IS NULL;

CREATE INDEX idx_relationships_source ON relationships(source_user_id);
CREATE INDEX idx_relationships_target ON relationships(target_user_id);
CREATE INDEX idx_relationships_type ON relationships(relationship_type);
CREATE INDEX idx_relationships_valid_range ON relationships USING GIST(valid_range);

-- User access cache (materialized permission lookups)
CREATE TABLE user_access_cache (
    viewer_user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    target_user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    access_tier SMALLINT NOT NULL CHECK (access_tier BETWEEN 1 AND 4),
    relationship_path UUID[] NOT NULL,
    hop_count SMALLINT NOT NULL,
    computed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (viewer_user_id, target_user_id)
);

CREATE INDEX idx_user_access_cache_viewer ON user_access_cache(viewer_user_id);
CREATE INDEX idx_user_access_cache_target ON user_access_cache(target_user_id);
CREATE INDEX idx_user_access_cache_tier ON user_access_cache(access_tier);
