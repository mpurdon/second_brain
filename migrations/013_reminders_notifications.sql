-- Reminders and Notifications System Migration
-- Supports proactive intelligence features

-- ===========================================
-- REMINDERS TABLE
-- ===========================================

-- Reminder trigger types
CREATE TYPE reminder_trigger_type AS ENUM (
    'time',           -- At a specific time
    'location',       -- When entering/leaving a location
    'event',          -- Before/after a calendar event
    'recurring'       -- Recurring schedule (daily, weekly, etc.)
);

-- Reminder status
CREATE TYPE reminder_status AS ENUM (
    'active',         -- Reminder is active and will trigger
    'triggered',      -- Reminder has been triggered, awaiting action
    'snoozed',        -- User snoozed the reminder
    'completed',      -- User marked as done
    'cancelled'       -- User cancelled the reminder
);

-- Main reminders table
CREATE TABLE reminders (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,

    -- Content
    title VARCHAR(255) NOT NULL,
    description TEXT,

    -- Trigger configuration
    trigger_type reminder_trigger_type NOT NULL DEFAULT 'time',
    trigger_config JSONB NOT NULL DEFAULT '{}',
    -- For 'time': {"at": "2024-01-15T09:00:00Z"}
    -- For 'location': {"location_id": "uuid", "action": "enter|leave", "radius_meters": 100}
    -- For 'event': {"event_id": "uuid", "offset_minutes": -15}
    -- For 'recurring': {"cron": "0 9 * * 1-5", "timezone": "America/New_York"}

    -- Scheduling
    next_trigger_at TIMESTAMPTZ,
    last_triggered_at TIMESTAMPTZ,

    -- Status
    status reminder_status NOT NULL DEFAULT 'active',
    snooze_until TIMESTAMPTZ,

    -- Related entities
    related_fact_id UUID REFERENCES facts(id) ON DELETE SET NULL,
    related_entity_id UUID REFERENCES entities(id) ON DELETE SET NULL,

    -- Metadata
    priority SMALLINT NOT NULL DEFAULT 3 CHECK (priority >= 1 AND priority <= 5),
    tags TEXT[] NOT NULL DEFAULT '{}',
    metadata JSONB NOT NULL DEFAULT '{}',

    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes for reminder queries
CREATE INDEX idx_reminders_user ON reminders(user_id);
CREATE INDEX idx_reminders_status ON reminders(status) WHERE status IN ('active', 'snoozed');
CREATE INDEX idx_reminders_next_trigger ON reminders(next_trigger_at) WHERE status = 'active';
CREATE INDEX idx_reminders_trigger_type ON reminders(trigger_type);

-- ===========================================
-- NOTIFICATIONS TABLE
-- ===========================================

-- Notification types
CREATE TYPE notification_type AS ENUM (
    'reminder',       -- From a reminder trigger
    'briefing',       -- Morning/evening briefing
    'calendar',       -- Calendar event reminder
    'birthday',       -- Birthday/anniversary notification
    'proactive',      -- Proactive insight from agents
    'system'          -- System notification
);

-- Notification delivery channels
CREATE TYPE notification_channel AS ENUM (
    'push',           -- Mobile push notification
    'email',          -- Email
    'discord',        -- Discord DM
    'alexa',          -- Alexa announcement
    'sms'             -- SMS (future)
);

-- Notification status
CREATE TYPE notification_status AS ENUM (
    'pending',        -- Queued for delivery
    'sent',           -- Delivered to channel
    'failed',         -- Delivery failed
    'read',           -- User read/acknowledged
    'dismissed'       -- User dismissed
);

-- Notifications table
CREATE TABLE notifications (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,

    -- Content
    notification_type notification_type NOT NULL,
    title VARCHAR(255) NOT NULL,
    body TEXT NOT NULL,

    -- Delivery
    channel notification_channel NOT NULL,
    status notification_status NOT NULL DEFAULT 'pending',

    -- Delivery tracking
    scheduled_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    sent_at TIMESTAMPTZ,
    read_at TIMESTAMPTZ,

    -- Related entities
    reminder_id UUID REFERENCES reminders(id) ON DELETE SET NULL,
    source_entity_id UUID,  -- Could be fact, entity, event, etc.
    source_entity_type VARCHAR(50),

    -- Delivery metadata
    delivery_metadata JSONB NOT NULL DEFAULT '{}',
    -- For push: {"device_token": "xxx", "message_id": "xxx"}
    -- For discord: {"channel_id": "xxx", "message_id": "xxx"}
    -- For email: {"message_id": "xxx"}

    -- Error tracking
    error_message TEXT,
    retry_count SMALLINT NOT NULL DEFAULT 0,

    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes for notification queries
CREATE INDEX idx_notifications_user ON notifications(user_id);
CREATE INDEX idx_notifications_status ON notifications(status) WHERE status = 'pending';
CREATE INDEX idx_notifications_scheduled ON notifications(scheduled_at) WHERE status = 'pending';
CREATE INDEX idx_notifications_channel ON notifications(channel);
CREATE INDEX idx_notifications_type ON notifications(notification_type);

-- ===========================================
-- USER NOTIFICATION PREFERENCES
-- ===========================================

CREATE TABLE user_notification_preferences (
    user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,

    -- Channel preferences
    push_enabled BOOLEAN NOT NULL DEFAULT true,
    email_enabled BOOLEAN NOT NULL DEFAULT true,
    discord_enabled BOOLEAN NOT NULL DEFAULT true,
    alexa_enabled BOOLEAN NOT NULL DEFAULT false,

    -- Quiet hours
    quiet_hours_enabled BOOLEAN NOT NULL DEFAULT false,
    quiet_hours_start TIME,  -- e.g., '22:00'
    quiet_hours_end TIME,    -- e.g., '07:00'

    -- Briefing preferences
    morning_briefing_enabled BOOLEAN NOT NULL DEFAULT true,
    morning_briefing_time TIME NOT NULL DEFAULT '07:00',
    evening_briefing_enabled BOOLEAN NOT NULL DEFAULT false,
    evening_briefing_time TIME NOT NULL DEFAULT '18:00',

    -- Timezone for scheduling
    timezone VARCHAR(50) NOT NULL DEFAULT 'America/New_York',

    -- Notification frequency limits
    max_notifications_per_hour SMALLINT NOT NULL DEFAULT 10,

    -- Updated timestamp
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ===========================================
-- BRIEFING HISTORY
-- ===========================================

CREATE TABLE briefing_history (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,

    -- Briefing type
    briefing_type VARCHAR(50) NOT NULL,  -- 'morning', 'evening', 'meeting_prep'

    -- Content
    content TEXT NOT NULL,

    -- What was included
    included_events INTEGER NOT NULL DEFAULT 0,
    included_reminders INTEGER NOT NULL DEFAULT 0,
    included_birthdays INTEGER NOT NULL DEFAULT 0,
    included_facts INTEGER NOT NULL DEFAULT 0,

    -- Generation metadata
    model_id VARCHAR(100),
    generation_time_ms INTEGER,

    -- Delivery
    delivered_via notification_channel,
    delivered_at TIMESTAMPTZ,

    -- Timestamps
    generated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_briefing_history_user ON briefing_history(user_id);
CREATE INDEX idx_briefing_history_date ON briefing_history(generated_at);

-- ===========================================
-- HELPER FUNCTIONS
-- ===========================================

-- Function to get users who need briefings at current hour
CREATE OR REPLACE FUNCTION get_users_for_briefing(
    p_briefing_type VARCHAR(50),
    p_current_hour INTEGER
)
RETURNS TABLE(
    user_id UUID,
    timezone VARCHAR(50),
    email VARCHAR(255)
) AS $$
BEGIN
    RETURN QUERY
    SELECT u.id, unp.timezone, u.email
    FROM users u
    JOIN user_notification_preferences unp ON unp.user_id = u.id
    WHERE
        CASE p_briefing_type
            WHEN 'morning' THEN
                unp.morning_briefing_enabled
                AND EXTRACT(HOUR FROM unp.morning_briefing_time) = p_current_hour
            WHEN 'evening' THEN
                unp.evening_briefing_enabled
                AND EXTRACT(HOUR FROM unp.evening_briefing_time) = p_current_hour
            ELSE false
        END;
END;
$$ LANGUAGE plpgsql STABLE;

-- Function to get pending reminders to evaluate
CREATE OR REPLACE FUNCTION get_pending_reminders(
    p_limit INTEGER DEFAULT 100
)
RETURNS TABLE(
    reminder_id UUID,
    user_id UUID,
    title VARCHAR(255),
    description TEXT,
    trigger_type reminder_trigger_type,
    trigger_config JSONB,
    priority SMALLINT
) AS $$
BEGIN
    RETURN QUERY
    SELECT r.id, r.user_id, r.title, r.description,
           r.trigger_type, r.trigger_config, r.priority
    FROM reminders r
    WHERE r.status = 'active'
    AND r.next_trigger_at <= NOW()
    ORDER BY r.priority DESC, r.next_trigger_at ASC
    LIMIT p_limit;
END;
$$ LANGUAGE plpgsql STABLE;

-- Function to calculate next trigger time for recurring reminders
CREATE OR REPLACE FUNCTION calculate_next_trigger(
    p_trigger_type reminder_trigger_type,
    p_trigger_config JSONB,
    p_last_triggered TIMESTAMPTZ DEFAULT NOW()
)
RETURNS TIMESTAMPTZ AS $$
DECLARE
    v_next TIMESTAMPTZ;
BEGIN
    CASE p_trigger_type
        WHEN 'time' THEN
            -- One-time trigger, no next
            v_next := NULL;
        WHEN 'recurring' THEN
            -- Simple recurring: add interval based on config
            -- For production, would use pg_cron or more sophisticated cron parsing
            v_next := p_last_triggered + COALESCE(
                (p_trigger_config->>'interval')::INTERVAL,
                '1 day'::INTERVAL
            );
        ELSE
            v_next := NULL;
    END CASE;

    RETURN v_next;
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- Trigger to update reminder next_trigger_at
CREATE OR REPLACE FUNCTION update_reminder_trigger()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.status = 'active' AND NEW.trigger_type = 'recurring' THEN
        NEW.next_trigger_at := calculate_next_trigger(
            NEW.trigger_type,
            NEW.trigger_config,
            COALESCE(NEW.last_triggered_at, NOW())
        );
    END IF;
    NEW.updated_at := NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_update_reminder_trigger
BEFORE UPDATE ON reminders
FOR EACH ROW
EXECUTE FUNCTION update_reminder_trigger();

-- ===========================================
-- DEFAULT DATA
-- ===========================================

-- Insert default notification preferences for existing users
INSERT INTO user_notification_preferences (user_id)
SELECT id FROM users
ON CONFLICT (user_id) DO NOTHING;

COMMENT ON TABLE reminders IS 'User reminders with various trigger types';
COMMENT ON TABLE notifications IS 'Notification queue and delivery tracking';
COMMENT ON TABLE user_notification_preferences IS 'Per-user notification settings';
COMMENT ON TABLE briefing_history IS 'History of generated briefings';
