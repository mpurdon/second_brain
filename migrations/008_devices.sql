-- Migration: 008_devices
-- Description: Create devices and conversations tables
-- Date: 2025-01

-- Device type enum
CREATE TYPE device_type AS ENUM ('alexa', 'discord', 'smart_mirror', 'mobile', 'web');

-- Device mode enum
CREATE TYPE device_mode AS ENUM ('personal', 'shared');

-- Devices table
CREATE TABLE devices (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Ownership
    family_id UUID REFERENCES families(id) ON DELETE CASCADE,
    registered_by UUID NOT NULL REFERENCES users(id),

    -- Device info
    device_type device_type NOT NULL,
    device_name VARCHAR(255) NOT NULL,
    device_identifier VARCHAR(500),

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

-- Device users (authorized users for a device)
CREATE TABLE device_users (
    device_id UUID NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,

    -- Voice profile ID for speaker recognition (Alexa)
    voice_profile_id VARCHAR(255),

    added_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (device_id, user_id)
);

CREATE INDEX idx_device_users_user ON device_users(user_id);

-- Conversations table (for context management)
CREATE TABLE conversations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    device_id UUID REFERENCES devices(id) ON DELETE SET NULL,

    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_message_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Context snapshot for resuming
    context_snapshot JSONB
);

CREATE INDEX idx_conversations_user ON conversations(user_id);
CREATE INDEX idx_conversations_recent ON conversations(user_id, last_message_at DESC);

-- Message role enum
CREATE TYPE message_role AS ENUM ('user', 'assistant', 'system');

-- Message modality enum
CREATE TYPE message_modality AS ENUM ('text', 'voice');

-- Messages table
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
