-- Migration: 004_entities
-- Description: Create entities tables (people, places, organizations, etc.)
-- Date: 2025-01

-- Entity type enum
CREATE TYPE entity_type AS ENUM (
    'person',
    'organization',
    'place',
    'project',
    'event',
    'product',
    'custom'
);

-- Entities table
CREATE TABLE entities (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Ownership
    owner_type VARCHAR(10) NOT NULL CHECK (owner_type IN ('user', 'family')),
    owner_id UUID NOT NULL,
    created_by UUID NOT NULL REFERENCES users(id),

    -- Entity data
    entity_type entity_type NOT NULL,
    name VARCHAR(500) NOT NULL,
    normalized_name VARCHAR(500) GENERATED ALWAYS AS (LOWER(TRIM(name))) STORED,
    aliases TEXT[] NOT NULL DEFAULT '{}',
    description TEXT,

    -- Visibility (for family-owned entities)
    visibility_tier SMALLINT NOT NULL DEFAULT 3 CHECK (visibility_tier BETWEEN 1 AND 4),

    -- Linking to users (for person entities that map to system users)
    linked_user_id UUID REFERENCES users(id),

    -- Metadata
    metadata JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT entities_name_not_empty CHECK (LENGTH(TRIM(name)) > 0)
);

CREATE INDEX idx_entities_owner ON entities(owner_type, owner_id);
CREATE INDEX idx_entities_type ON entities(entity_type);
CREATE INDEX idx_entities_name_trgm ON entities USING GIN(normalized_name gin_trgm_ops);
CREATE INDEX idx_entities_aliases ON entities USING GIN(aliases);
CREATE INDEX idx_entities_linked_user ON entities(linked_user_id) WHERE linked_user_id IS NOT NULL;

-- Entity attributes (temporal attributes like phone numbers, job titles)
CREATE TABLE entity_attributes (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    entity_id UUID NOT NULL REFERENCES entities(id) ON DELETE CASCADE,

    attribute_name VARCHAR(100) NOT NULL,
    attribute_value TEXT NOT NULL,

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

    -- Visibility
    visibility_tier SMALLINT NOT NULL DEFAULT 2 CHECK (visibility_tier BETWEEN 1 AND 4),

    -- Audit
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by UUID REFERENCES users(id),
    superseded_by UUID REFERENCES entity_attributes(id)
);

CREATE INDEX idx_entity_attributes_entity ON entity_attributes(entity_id);
CREATE INDEX idx_entity_attributes_name ON entity_attributes(attribute_name);
CREATE INDEX idx_entity_attributes_valid ON entity_attributes USING GIST(valid_range);
CREATE INDEX idx_entity_attributes_current ON entity_attributes(entity_id, attribute_name)
    WHERE valid_to IS NULL;

-- Entity locations (PostGIS geography)
CREATE TABLE entity_locations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    entity_id UUID NOT NULL REFERENCES entities(id) ON DELETE CASCADE,

    -- Location label
    label VARCHAR(100) NOT NULL,

    -- Address data
    address_raw TEXT,
    address_normalized JSONB,

    -- PostGIS geography (WGS84)
    location GEOGRAPHY(POINT, 4326),

    -- Geocoding metadata
    geocode_source VARCHAR(50),
    geocode_confidence DECIMAL(3,2),
    geocoded_at TIMESTAMPTZ,

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

    -- Visibility
    visibility_tier SMALLINT NOT NULL DEFAULT 3 CHECK (visibility_tier BETWEEN 1 AND 4),

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_entity_locations_entity ON entity_locations(entity_id);
CREATE INDEX idx_entity_locations_label ON entity_locations(label);
CREATE INDEX idx_entity_locations_geo ON entity_locations USING GIST(location);
CREATE INDEX idx_entity_locations_valid ON entity_locations USING GIST(valid_range);
CREATE INDEX idx_entity_locations_current ON entity_locations(entity_id, label)
    WHERE valid_to IS NULL;
