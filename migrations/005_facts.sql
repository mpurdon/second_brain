-- Migration: 005_facts
-- Description: Create facts and embeddings tables
-- Date: 2025-01

-- Fact source enum
CREATE TYPE fact_source AS ENUM ('voice', 'text', 'import', 'calendar', 'inferred');

-- Facts table
CREATE TABLE facts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Ownership
    owner_type VARCHAR(10) NOT NULL CHECK (owner_type IN ('user', 'family')),
    owner_id UUID NOT NULL,
    created_by UUID NOT NULL REFERENCES users(id),

    -- Content
    content TEXT NOT NULL,
    content_normalized TEXT GENERATED ALWAYS AS (LOWER(TRIM(content))) STORED,
    source fact_source NOT NULL DEFAULT 'text',

    -- Classification
    importance SMALLINT NOT NULL DEFAULT 3 CHECK (importance BETWEEN 1 AND 5),
    confidence DECIMAL(3,2) NOT NULL DEFAULT 1.0 CHECK (confidence BETWEEN 0 AND 1),
    visibility_tier SMALLINT NOT NULL DEFAULT 2 CHECK (visibility_tier BETWEEN 1 AND 4),

    -- About a specific entity (optional)
    about_entity_id UUID REFERENCES entities(id),

    -- Temporal validity (when the fact is/was true)
    valid_from DATE,
    valid_to DATE,
    valid_range TSTZRANGE GENERATED ALWAYS AS (
        TSTZRANGE(
            COALESCE(valid_from, '-infinity')::TIMESTAMPTZ,
            COALESCE(valid_to, 'infinity')::TIMESTAMPTZ,
            '[)'
        )
    ) STORED,

    -- Recurrence
    is_recurring BOOLEAN NOT NULL DEFAULT false,
    recurrence_rule TEXT,

    -- Audit
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    superseded_by UUID REFERENCES facts(id),

    CONSTRAINT facts_content_not_empty CHECK (LENGTH(TRIM(content)) > 0)
);

CREATE INDEX idx_facts_owner ON facts(owner_type, owner_id);
CREATE INDEX idx_facts_about_entity ON facts(about_entity_id) WHERE about_entity_id IS NOT NULL;
CREATE INDEX idx_facts_importance ON facts(importance);
CREATE INDEX idx_facts_visibility ON facts(visibility_tier);
CREATE INDEX idx_facts_valid_range ON facts USING GIST(valid_range);
CREATE INDEX idx_facts_current ON facts(owner_type, owner_id) WHERE valid_to IS NULL;
CREATE INDEX idx_facts_recurring ON facts(is_recurring) WHERE is_recurring = true;
CREATE INDEX idx_facts_content_trgm ON facts USING GIN(content_normalized gin_trgm_ops);

-- Fact embeddings (pgvector)
CREATE TABLE fact_embeddings (
    fact_id UUID PRIMARY KEY REFERENCES facts(id) ON DELETE CASCADE,
    embedding VECTOR(1024) NOT NULL,
    model_id VARCHAR(100) NOT NULL DEFAULT 'amazon.titan-embed-text-v2:0',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- HNSW index for fast approximate nearest neighbor search
CREATE INDEX idx_fact_embeddings_vector ON fact_embeddings
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- Mention role enum
CREATE TYPE mention_role AS ENUM ('subject', 'object', 'location', 'organization', 'reference');

-- Entity mentions (links facts to entities)
CREATE TABLE entity_mentions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    fact_id UUID NOT NULL REFERENCES facts(id) ON DELETE CASCADE,
    entity_id UUID NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    role mention_role NOT NULL DEFAULT 'reference',
    confidence DECIMAL(3,2) NOT NULL DEFAULT 1.0,

    -- Position in text (for highlighting)
    start_offset INT,
    end_offset INT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT entity_mentions_unique UNIQUE (fact_id, entity_id, role)
);

CREATE INDEX idx_entity_mentions_fact ON entity_mentions(fact_id);
CREATE INDEX idx_entity_mentions_entity ON entity_mentions(entity_id);
