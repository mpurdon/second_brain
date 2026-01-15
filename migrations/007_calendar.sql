-- Migration: 007_calendar
-- Description: Create calendar events and reminders tables
-- Date: 2025-01

-- Calendar events table
CREATE TABLE calendar_events (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Ownership
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,

    -- External reference
    external_id VARCHAR(255),
    external_provider VARCHAR(50),
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

-- Calendar event attendees
CREATE TABLE calendar_event_attendees (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    event_id UUID NOT NULL REFERENCES calendar_events(id) ON DELETE CASCADE,
    entity_id UUID REFERENCES entities(id) ON DELETE SET NULL,

    -- External attendee info (if not linked to entity)
    email VARCHAR(255),
    display_name VARCHAR(255),

    -- Status
    response_status VARCHAR(20) DEFAULT 'unknown'
);

-- Unique attendee per event (by entity or by email)
CREATE UNIQUE INDEX idx_calendar_event_attendees_unique ON calendar_event_attendees(
    event_id,
    COALESCE(entity_id, '00000000-0000-0000-0000-000000000000'::UUID),
    COALESCE(email, '')
);

CREATE INDEX idx_calendar_event_attendees_event ON calendar_event_attendees(event_id);
CREATE INDEX idx_calendar_event_attendees_entity ON calendar_event_attendees(entity_id);

-- Reminder status enum
CREATE TYPE reminder_status AS ENUM ('pending', 'sent', 'acknowledged', 'snoozed', 'cancelled');

-- Reminder type enum
CREATE TYPE reminder_type AS ENUM ('birthday', 'anniversary', 'deadline', 'follow_up', 'custom', 'briefing');

-- Reminders table
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
