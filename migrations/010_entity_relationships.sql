-- Migration: 010_entity_relationships
-- Description: Create entity-to-entity relationships table
-- Date: 2025-01

-- Entity relationships (links entities to other entities)
CREATE TABLE entity_relationships (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_entity_id UUID NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    target_entity_id UUID NOT NULL REFERENCES entities(id) ON DELETE CASCADE,

    -- Relationship type (e.g., 'works_at', 'parent_of', 'member_of', 'located_in')
    relationship_type VARCHAR(100) NOT NULL,

    -- Temporal validity
    valid_from DATE,
    valid_to DATE,

    -- Additional metadata
    metadata JSONB NOT NULL DEFAULT '{}',

    -- Audit
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by UUID REFERENCES users(id),

    CONSTRAINT entity_relationships_no_self CHECK (source_entity_id != target_entity_id)
);

CREATE INDEX idx_entity_relationships_source ON entity_relationships(source_entity_id);
CREATE INDEX idx_entity_relationships_target ON entity_relationships(target_entity_id);
CREATE INDEX idx_entity_relationships_type ON entity_relationships(relationship_type);
CREATE INDEX idx_entity_relationships_valid_from ON entity_relationships(valid_from);
CREATE INDEX idx_entity_relationships_valid_to ON entity_relationships(valid_to);
CREATE UNIQUE INDEX idx_entity_relationships_unique_active ON entity_relationships(
    source_entity_id, target_entity_id, relationship_type
) WHERE valid_to IS NULL;

-- Common relationship types for reference:
-- Person relationships: 'parent_of', 'child_of', 'spouse_of', 'sibling_of', 'friend_of'
-- Work relationships: 'works_at', 'manages', 'member_of', 'founded'
-- Location relationships: 'located_in', 'lives_at', 'works_at'
-- Event relationships: 'attends', 'organizes', 'participates_in'
-- Project relationships: 'works_on', 'owns', 'contributes_to'
