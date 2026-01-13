# PostgreSQL Schema Design

**Version:** 1.0
**Date:** January 2025
**Status:** Draft

---

## Overview

This document defines the PostgreSQL schema for the Second Brain application. The schema supports:

- Multi-tenant user and family management
- Relationship graph with tiered access control
- Facts with temporal validity and vector embeddings
- Geographic locations with PostGIS
- Calendar events and reminders
- Device management
- Tagging and taxonomy

---

## Extensions Required

```sql
-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";      -- UUID generation
CREATE EXTENSION IF NOT EXISTS "pgvector";        -- Vector similarity search
CREATE EXTENSION IF NOT EXISTS "postgis";         -- Geographic queries
CREATE EXTENSION IF NOT EXISTS "btree_gist";      -- Temporal range indexes
CREATE EXTENSION IF NOT EXISTS "pg_trgm";         -- Fuzzy text matching
```

---

## Schema Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              CORE ENTITIES                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌──────────┐     ┌──────────────┐     ┌──────────┐                        │
│  │  users   │────<│family_members│>────│ families │                        │
│  └────┬─────┘     └──────────────┘     └──────────┘                        │
│       │                                                                     │
│       │ ┌────────────────┐                                                 │
│       └─│ relationships  │ (user-to-user graph with access tiers)          │
│         └───────┬────────┘                                                 │
│                 │                                                           │
│  ┌──────────────┴───────────────┐                                          │
│  │      user_access_cache       │ (materialized permission lookups)        │
│  └──────────────────────────────┘                                          │
│                                                                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                            KNOWLEDGE GRAPH                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌──────────┐     ┌────────────────┐     ┌──────────┐                      │
│  │ entities │────<│ entity_mentions│>────│  facts   │                      │
│  └────┬─────┘     └────────────────┘     └────┬─────┘                      │
│       │                                       │                             │
│       │ ┌──────────────────┐                 │ ┌──────────┐                │
│       ├─│ entity_locations │                 ├─│ fact_tags│                │
│       │ └──────────────────┘                 │ └──────────┘                │
│       │                                       │                             │
│       │ ┌──────────────────┐                 │ ┌──────────────────┐        │
│       └─│entity_attributes │                 └─│ fact_embeddings  │        │
│         └──────────────────┘                   └──────────────────┘        │
│                                                                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                         CALENDAR & REMINDERS                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────┐     ┌──────────┐                                      │
│  │ calendar_events │     │ reminders│                                      │
│  └─────────────────┘     └──────────┘                                      │
│                                                                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                              DEVICES                                        │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌──────────┐     ┌───────────────────┐                                    │
│  │ devices  │────<│ device_users      │                                    │
│  └──────────┘     └───────────────────┘                                    │
│                                                                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                              TAXONOMY                                       │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌──────────┐                                                              │
│  │   tags   │ (hierarchical with ltree-style paths)                        │
│  └──────────┘                                                              │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Table Definitions

### 1. Users & Families

#### 1.1 families

```sql
CREATE TABLE families (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    settings JSONB NOT NULL DEFAULT '{}',
    -- Settings includes: timezone, notification preferences, etc.

    CONSTRAINT families_name_not_empty CHECK (LENGTH(TRIM(name)) > 0)
);

CREATE INDEX idx_families_created_at ON families(created_at);
```

#### 1.2 users

```sql
CREATE TYPE user_status AS ENUM ('active', 'inactive', 'suspended');

CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    cognito_sub VARCHAR(255) UNIQUE NOT NULL,  -- Cognito user ID
    email VARCHAR(255) NOT NULL,
    display_name VARCHAR(255) NOT NULL,
    avatar_url TEXT,
    status user_status NOT NULL DEFAULT 'active',
    settings JSONB NOT NULL DEFAULT '{}',
    -- Settings includes: timezone, language, notification prefs
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_active_at TIMESTAMPTZ,

    CONSTRAINT users_email_valid CHECK (email ~* '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$')
);

CREATE UNIQUE INDEX idx_users_email ON users(LOWER(email));
CREATE INDEX idx_users_cognito_sub ON users(cognito_sub);
CREATE INDEX idx_users_status ON users(status) WHERE status = 'active';
```

#### 1.3 family_members

```sql
CREATE TYPE family_role AS ENUM ('admin', 'member', 'child');

CREATE TABLE family_members (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    family_id UUID NOT NULL REFERENCES families(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role family_role NOT NULL DEFAULT 'member',
    joined_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    invited_by UUID REFERENCES users(id),

    CONSTRAINT family_members_unique UNIQUE (family_id, user_id)
);

CREATE INDEX idx_family_members_family ON family_members(family_id);
CREATE INDEX idx_family_members_user ON family_members(user_id);
```

---

### 2. Relationship Graph

#### 2.1 relationships

Stores user-to-user relationships with access tiers and temporal validity.

```sql
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

CREATE TABLE relationships (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    target_user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    relationship_type relationship_type NOT NULL,
    custom_type_name VARCHAR(100),  -- For 'custom' type
    access_tier SMALLINT NOT NULL DEFAULT 3 CHECK (access_tier BETWEEN 1 AND 4),
    -- Tier 1: Full, Tier 2: Personal, Tier 3: Events/Milestones, Tier 4: Basic

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
```

#### 2.2 user_access_cache

Materialized view of "who can see whom at what tier" for fast permission checks.

```sql
CREATE TABLE user_access_cache (
    viewer_user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    target_user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    access_tier SMALLINT NOT NULL CHECK (access_tier BETWEEN 1 AND 4),
    relationship_path UUID[] NOT NULL,  -- Array of relationship IDs traversed
    hop_count SMALLINT NOT NULL,
    computed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (viewer_user_id, target_user_id)
);

CREATE INDEX idx_user_access_cache_viewer ON user_access_cache(viewer_user_id);
CREATE INDEX idx_user_access_cache_target ON user_access_cache(target_user_id);
CREATE INDEX idx_user_access_cache_tier ON user_access_cache(access_tier);
```

#### 2.3 Relationship Cache Refresh Function

```sql
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
            GREATEST(au.access_tier, r.access_tier) AS access_tier,  -- Most restrictive
            au.relationship_path || r.id,
            au.hop_count + 1
        FROM accessible_users au
        JOIN relationships r ON r.source_user_id = au.target_user_id
        WHERE au.hop_count < 4
          AND NOT r.target_user_id = ANY(
              SELECT users.id FROM users, unnest(au.relationship_path) AS rel_id
              JOIN relationships ON relationships.id = rel_id
              WHERE relationships.target_user_id = users.id
          )  -- Prevent cycles
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

-- Trigger to refresh cache when relationships change
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

CREATE TRIGGER relationships_cache_refresh
AFTER INSERT OR UPDATE OR DELETE ON relationships
FOR EACH ROW EXECUTE FUNCTION trigger_refresh_access_cache();
```

---

### 3. Entities

#### 3.1 entities

People, places, organizations, projects, etc. that facts reference.

```sql
CREATE TYPE entity_type AS ENUM (
    'person',
    'organization',
    'place',
    'project',
    'event',
    'product',
    'custom'
);

CREATE TABLE entities (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Ownership
    owner_type VARCHAR(10) NOT NULL CHECK (owner_type IN ('user', 'family')),
    owner_id UUID NOT NULL,  -- user_id or family_id
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
```

#### 3.2 entity_attributes

Temporal attributes for entities (phone numbers, job titles, etc.).

```sql
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
```

#### 3.3 entity_locations

Geographic locations for entities using PostGIS.

```sql
CREATE TABLE entity_locations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    entity_id UUID NOT NULL REFERENCES entities(id) ON DELETE CASCADE,

    -- Location label
    label VARCHAR(100) NOT NULL,  -- 'home', 'work', 'school', etc.

    -- Address data
    address_raw TEXT,
    address_normalized JSONB,  -- {street, city, state, zip, country}

    -- PostGIS geography (WGS84)
    location GEOGRAPHY(POINT, 4326),

    -- Geocoding metadata
    geocode_source VARCHAR(50),  -- 'aws_location', 'manual', etc.
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
```

---

### 4. Facts

#### 4.1 facts

Core knowledge storage with temporal validity and embeddings.

```sql
CREATE TYPE fact_source AS ENUM ('voice', 'text', 'import', 'calendar', 'inferred');

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
    recurrence_rule TEXT,  -- iCal RRULE format

    -- Audit
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),  -- When we learned this
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
```

#### 4.2 fact_embeddings

Vector embeddings for semantic search.

```sql
CREATE TABLE fact_embeddings (
    fact_id UUID PRIMARY KEY REFERENCES facts(id) ON DELETE CASCADE,
    embedding VECTOR(1024) NOT NULL,  -- Titan Embeddings V2
    model_id VARCHAR(100) NOT NULL DEFAULT 'amazon.titan-embed-text-v2:0',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- HNSW index for fast approximate nearest neighbor search
CREATE INDEX idx_fact_embeddings_vector ON fact_embeddings
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);
```

#### 4.3 entity_mentions

Links facts to entities they mention.

```sql
CREATE TYPE mention_role AS ENUM ('subject', 'object', 'location', 'organization', 'reference');

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
```

---

### 5. Tags & Taxonomy

#### 5.1 tags

Hierarchical tagging system.

```sql
CREATE TABLE tags (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Ownership (NULL = system-wide)
    owner_type VARCHAR(10) CHECK (owner_type IN ('user', 'family', NULL)),
    owner_id UUID,

    -- Tag hierarchy using path
    name VARCHAR(100) NOT NULL,
    path VARCHAR(500) NOT NULL,  -- e.g., 'domain/work/meetings'
    parent_id UUID REFERENCES tags(id),

    -- Metadata
    description TEXT,
    color VARCHAR(7),  -- Hex color for UI
    icon VARCHAR(50),  -- Icon identifier

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT tags_path_format CHECK (path ~ '^[a-z0-9_/]+$'),
    CONSTRAINT tags_unique_path UNIQUE (COALESCE(owner_type, ''), COALESCE(owner_id, '00000000-0000-0000-0000-000000000000'::UUID), path)
);

CREATE INDEX idx_tags_owner ON tags(owner_type, owner_id);
CREATE INDEX idx_tags_parent ON tags(parent_id);
CREATE INDEX idx_tags_path ON tags(path);
CREATE INDEX idx_tags_path_prefix ON tags(path varchar_pattern_ops);  -- For LIKE 'prefix%'
```

#### 5.2 fact_tags

Many-to-many relationship between facts and tags.

```sql
CREATE TABLE fact_tags (
    fact_id UUID NOT NULL REFERENCES facts(id) ON DELETE CASCADE,
    tag_id UUID NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    confidence DECIMAL(3,2) NOT NULL DEFAULT 1.0,
    assigned_by VARCHAR(20) NOT NULL DEFAULT 'agent' CHECK (assigned_by IN ('agent', 'user')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (fact_id, tag_id)
);

CREATE INDEX idx_fact_tags_tag ON fact_tags(tag_id);
```

---

### 6. Calendar & Reminders

#### 6.1 calendar_events

Synced calendar events from external providers.

```sql
CREATE TABLE calendar_events (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Ownership
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,

    -- External reference
    external_id VARCHAR(255),
    external_provider VARCHAR(50),  -- 'google', 'outlook'
    external_calendar_id VARCHAR(255),

    -- Event data
    title VARCHAR(500) NOT NULL,
    description TEXT,
    location TEXT,

    -- Timing
    start_time TIMESTAMPTZ NOT NULL,
    end_time TIMESTAMPTZ NOT NULL,
    all_day BOOLEAN NOT NULL DEFAULT false,
    timezone VARCHAR(50),

    -- Recurrence
    is_recurring BOOLEAN NOT NULL DEFAULT false,
    recurrence_rule TEXT,
    recurring_event_id UUID REFERENCES calendar_events(id),

    -- Visibility
    visibility_tier SMALLINT NOT NULL DEFAULT 3 CHECK (visibility_tier BETWEEN 1 AND 4),

    -- Sync metadata
    synced_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    etag VARCHAR(255),

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT calendar_events_external_unique UNIQUE (user_id, external_provider, external_id)
);

CREATE INDEX idx_calendar_events_user ON calendar_events(user_id);
CREATE INDEX idx_calendar_events_time ON calendar_events(start_time, end_time);
CREATE INDEX idx_calendar_events_user_time ON calendar_events(user_id, start_time);
```

#### 6.2 calendar_event_attendees

Links calendar events to entities.

```sql
CREATE TABLE calendar_event_attendees (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    event_id UUID NOT NULL REFERENCES calendar_events(id) ON DELETE CASCADE,
    entity_id UUID REFERENCES entities(id) ON DELETE SET NULL,

    -- External attendee info (if not linked to entity)
    email VARCHAR(255),
    display_name VARCHAR(255),

    -- Status
    response_status VARCHAR(20) DEFAULT 'unknown',  -- 'accepted', 'declined', 'tentative', 'unknown'

    CONSTRAINT calendar_event_attendees_unique UNIQUE (event_id, COALESCE(entity_id, '00000000-0000-0000-0000-000000000000'::UUID), COALESCE(email, ''))
);

CREATE INDEX idx_calendar_event_attendees_event ON calendar_event_attendees(event_id);
CREATE INDEX idx_calendar_event_attendees_entity ON calendar_event_attendees(entity_id);
```

#### 6.3 reminders

Proactive reminders and notifications.

```sql
CREATE TYPE reminder_status AS ENUM ('pending', 'sent', 'acknowledged', 'snoozed', 'cancelled');
CREATE TYPE reminder_type AS ENUM ('birthday', 'anniversary', 'deadline', 'follow_up', 'custom', 'briefing');

CREATE TABLE reminders (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Target user
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,

    -- What triggered this reminder
    reminder_type reminder_type NOT NULL,

    -- Links to source (optional)
    source_fact_id UUID REFERENCES facts(id) ON DELETE SET NULL,
    source_entity_id UUID REFERENCES entities(id) ON DELETE SET NULL,
    source_event_id UUID REFERENCES calendar_events(id) ON DELETE SET NULL,

    -- Content
    title VARCHAR(500) NOT NULL,
    body TEXT,

    -- Timing
    remind_at TIMESTAMPTZ NOT NULL,

    -- Status
    status reminder_status NOT NULL DEFAULT 'pending',
    sent_at TIMESTAMPTZ,
    acknowledged_at TIMESTAMPTZ,
    snoozed_until TIMESTAMPTZ,

    -- Recurrence
    is_recurring BOOLEAN NOT NULL DEFAULT false,
    recurrence_rule TEXT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_reminders_user ON reminders(user_id);
CREATE INDEX idx_reminders_pending ON reminders(remind_at) WHERE status = 'pending';
CREATE INDEX idx_reminders_user_pending ON reminders(user_id, remind_at) WHERE status = 'pending';
```

---

### 7. Devices

#### 7.1 devices

Registered devices (Alexa, Smart Mirror, etc.).

```sql
CREATE TYPE device_type AS ENUM ('alexa', 'discord', 'smart_mirror', 'mobile', 'web');
CREATE TYPE device_mode AS ENUM ('personal', 'shared');

CREATE TABLE devices (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Ownership
    family_id UUID REFERENCES families(id) ON DELETE CASCADE,
    registered_by UUID NOT NULL REFERENCES users(id),

    -- Device info
    device_type device_type NOT NULL,
    device_name VARCHAR(255) NOT NULL,
    device_identifier VARCHAR(500),  -- External device ID

    -- Mode
    mode device_mode NOT NULL DEFAULT 'shared',
    max_visibility_tier SMALLINT NOT NULL DEFAULT 3 CHECK (max_visibility_tier BETWEEN 1 AND 4),

    -- Permissions
    permissions JSONB NOT NULL DEFAULT '{
        "can_ingest_facts": true,
        "can_create_reminders": true,
        "can_query": true,
        "voice_profiles_enabled": false
    }',

    -- Status
    is_active BOOLEAN NOT NULL DEFAULT true,
    last_seen_at TIMESTAMPTZ,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_devices_family ON devices(family_id);
CREATE INDEX idx_devices_type ON devices(device_type);
CREATE INDEX idx_devices_identifier ON devices(device_identifier) WHERE device_identifier IS NOT NULL;
```

#### 7.2 device_users

Links devices to authorized users.

```sql
CREATE TABLE device_users (
    device_id UUID NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,

    -- Voice profile ID for speaker recognition (Alexa)
    voice_profile_id VARCHAR(255),

    added_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (device_id, user_id)
);

CREATE INDEX idx_device_users_user ON device_users(user_id);
```

---

### 8. Audit & Sessions

#### 8.1 conversations

Conversation history for context.

```sql
CREATE TABLE conversations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    device_id UUID REFERENCES devices(id) ON DELETE SET NULL,

    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_message_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Context snapshot for resuming
    context_snapshot JSONB,

    -- Never shared - always private
    CONSTRAINT conversations_always_private CHECK (true)
);

CREATE INDEX idx_conversations_user ON conversations(user_id);
CREATE INDEX idx_conversations_recent ON conversations(user_id, last_message_at DESC);
```

#### 8.2 messages

Individual messages in conversations.

```sql
CREATE TYPE message_role AS ENUM ('user', 'assistant', 'system');
CREATE TYPE message_modality AS ENUM ('text', 'voice');

CREATE TABLE messages (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,

    role message_role NOT NULL,
    content TEXT NOT NULL,

    -- Modality
    input_modality message_modality,
    output_modality message_modality,

    -- Metrics
    tokens_in INT,
    tokens_out INT,
    model_id VARCHAR(100),
    latency_ms INT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_messages_conversation ON messages(conversation_id, created_at);
```

---

## Common Queries

### 1. Get all facts visible to a user about a specific entity

```sql
SELECT f.*
FROM facts f
LEFT JOIN user_access_cache uac
    ON f.owner_type = 'user'
    AND f.owner_id = uac.target_user_id
    AND uac.viewer_user_id = :current_user_id
WHERE
    f.about_entity_id = :entity_id
    AND (
        -- User owns the fact
        (f.owner_type = 'user' AND f.owner_id = :current_user_id)
        -- Or family owns it and user is in family
        OR (f.owner_type = 'family' AND f.owner_id IN (
            SELECT family_id FROM family_members WHERE user_id = :current_user_id
        ))
        -- Or user has access via relationship graph
        OR (f.owner_type = 'user' AND uac.access_tier <= f.visibility_tier)
    )
    AND (f.valid_to IS NULL OR f.valid_to > CURRENT_DATE)
ORDER BY f.importance DESC, f.recorded_at DESC;
```

### 2. Semantic search with permission filtering

```sql
WITH query_embedding AS (
    SELECT :embedding::vector AS vec
)
SELECT
    f.id,
    f.content,
    f.importance,
    1 - (fe.embedding <=> qe.vec) AS similarity
FROM facts f
JOIN fact_embeddings fe ON fe.fact_id = f.id
CROSS JOIN query_embedding qe
LEFT JOIN user_access_cache uac
    ON f.owner_type = 'user'
    AND f.owner_id = uac.target_user_id
    AND uac.viewer_user_id = :current_user_id
WHERE
    (
        (f.owner_type = 'user' AND f.owner_id = :current_user_id)
        OR (f.owner_type = 'family' AND f.owner_id IN (
            SELECT family_id FROM family_members WHERE user_id = :current_user_id
        ))
        OR (f.owner_type = 'user' AND uac.access_tier <= f.visibility_tier)
    )
    AND (f.valid_to IS NULL OR f.valid_to > CURRENT_DATE)
ORDER BY fe.embedding <=> qe.vec
LIMIT 10;
```

### 3. Friends within walking distance

```sql
WITH my_home AS (
    SELECT el.location
    FROM entity_locations el
    JOIN entities e ON e.id = el.entity_id
    WHERE e.linked_user_id = :user_id
      AND el.label = 'home'
      AND el.valid_to IS NULL
    LIMIT 1
)
SELECT
    e.name,
    el.label,
    ST_Distance(el.location, mh.location) AS distance_meters
FROM entities e
JOIN relationships r ON r.target_user_id = e.linked_user_id
JOIN entity_locations el ON el.entity_id = e.id
CROSS JOIN my_home mh
WHERE r.source_user_id = :user_id
  AND r.relationship_type = 'friend'
  AND el.label = 'home'
  AND el.valid_to IS NULL
  AND ST_DWithin(el.location, mh.location, :max_distance_meters)
ORDER BY distance_meters;
```

### 4. Point-in-time query (coworkers in 1996)

```sql
SELECT DISTINCT e.name
FROM relationships r1
JOIN relationships r2 ON r2.target_user_id = r1.target_user_id  -- Same company
JOIN entities e ON e.linked_user_id = r2.source_user_id
WHERE r1.source_user_id = :my_user_id
  AND r1.relationship_type = 'colleague'
  AND r1.valid_range @> '1996-06-01'::timestamptz
  AND r2.relationship_type = 'colleague'
  AND r2.valid_range @> '1996-06-01'::timestamptz
  AND r2.source_user_id != :my_user_id;
```

---

## Indexes Summary

| Table | Index | Type | Purpose |
|-------|-------|------|---------|
| fact_embeddings | embedding | HNSW | Vector similarity search |
| entity_locations | location | GIST | Spatial proximity queries |
| facts | valid_range | GIST | Temporal range queries |
| relationships | valid_range | GIST | Temporal range queries |
| entities | normalized_name | GIN (trgm) | Fuzzy text search |
| facts | content_normalized | GIN (trgm) | Fuzzy text search |
| tags | path | B-tree pattern | Hierarchical tag queries |

---

## Migration Strategy

1. **Initial Setup**: Create extensions, enums, and tables in dependency order
2. **Seed Data**: Create system-wide tags, default settings
3. **Index Creation**: Create indexes after initial data load for performance

---

*Document Version: 1.0*
*Schema supports: Multi-tenant, temporal, spatial, and semantic queries*
