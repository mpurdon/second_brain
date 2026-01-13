-- Migration: 006_tags
-- Description: Create tags and taxonomy tables
-- Date: 2025-01

-- Tags table (hierarchical)
CREATE TABLE tags (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Ownership (NULL = system-wide)
    owner_type VARCHAR(10) CHECK (owner_type IN ('user', 'family')),
    owner_id UUID,

    -- Tag hierarchy using path
    name VARCHAR(100) NOT NULL,
    path VARCHAR(500) NOT NULL,
    parent_id UUID REFERENCES tags(id),

    -- Metadata
    description TEXT,
    color VARCHAR(7),
    icon VARCHAR(50),

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT tags_path_format CHECK (path ~ '^[a-z0-9_/]+$'),
    CONSTRAINT tags_unique_path UNIQUE (
        COALESCE(owner_type, ''),
        COALESCE(owner_id, '00000000-0000-0000-0000-000000000000'::UUID),
        path
    )
);

CREATE INDEX idx_tags_owner ON tags(owner_type, owner_id);
CREATE INDEX idx_tags_parent ON tags(parent_id);
CREATE INDEX idx_tags_path ON tags(path);
CREATE INDEX idx_tags_path_prefix ON tags(path varchar_pattern_ops);

-- Fact tags (many-to-many)
CREATE TABLE fact_tags (
    fact_id UUID NOT NULL REFERENCES facts(id) ON DELETE CASCADE,
    tag_id UUID NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    confidence DECIMAL(3,2) NOT NULL DEFAULT 1.0,
    assigned_by VARCHAR(20) NOT NULL DEFAULT 'agent' CHECK (assigned_by IN ('agent', 'user')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (fact_id, tag_id)
);

CREATE INDEX idx_fact_tags_tag ON fact_tags(tag_id);

-- Insert default system tags
INSERT INTO tags (name, path, description) VALUES
    ('entity_type', 'entity_type', 'Entity type tags'),
    ('person', 'entity_type/person', 'Person entities'),
    ('organization', 'entity_type/organization', 'Organization entities'),
    ('place', 'entity_type/place', 'Place entities'),
    ('project', 'entity_type/project', 'Project entities'),
    ('event', 'entity_type/event', 'Event entities'),
    ('domain', 'domain', 'Domain tags'),
    ('work', 'domain/work', 'Work-related'),
    ('personal', 'domain/personal', 'Personal'),
    ('family', 'domain/family', 'Family-related'),
    ('hobby', 'domain/hobby', 'Hobbies'),
    ('temporal', 'temporal', 'Temporal tags'),
    ('recurring', 'temporal/recurring', 'Recurring events'),
    ('deadline', 'temporal/deadline', 'Deadlines'),
    ('milestone', 'temporal/milestone', 'Milestones'),
    ('anniversary', 'temporal/anniversary', 'Anniversaries'),
    ('priority', 'priority', 'Priority tags'),
    ('critical', 'priority/critical', 'Critical priority'),
    ('high', 'priority/high', 'High priority'),
    ('medium', 'priority/medium', 'Medium priority'),
    ('low', 'priority/low', 'Low priority');
