-- User Feedback System Migration
-- Tracks user interactions for learning and improvement

-- Feedback events table
CREATE TABLE user_feedback (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,

    -- What type of feedback
    feedback_type VARCHAR(50) NOT NULL,  -- 'query_satisfaction', 'tag_acceptance', 'notification_action', 'suggestion_action'

    -- Context about what was being rated
    context_type VARCHAR(50) NOT NULL,   -- 'query', 'tag_suggestion', 'notification', 'briefing'
    context_id UUID,                      -- ID of the related entity (query session, fact, notification, etc.)

    -- The actual feedback
    action VARCHAR(50) NOT NULL,          -- 'accepted', 'rejected', 'dismissed', 'thumbs_up', 'thumbs_down', 'modified'
    rating SMALLINT,                      -- Optional 1-5 rating

    -- Additional context
    metadata JSONB NOT NULL DEFAULT '{}', -- Stores additional context (e.g., original suggestion, modified value)

    -- Timing
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Indexing
    CONSTRAINT valid_rating CHECK (rating IS NULL OR (rating >= 1 AND rating <= 5))
);

-- Indexes for analytics
CREATE INDEX idx_user_feedback_user ON user_feedback(user_id);
CREATE INDEX idx_user_feedback_type ON user_feedback(feedback_type);
CREATE INDEX idx_user_feedback_context ON user_feedback(context_type, context_id);
CREATE INDEX idx_user_feedback_created ON user_feedback(created_at);
CREATE INDEX idx_user_feedback_action ON user_feedback(action);

-- Aggregated feedback stats per user (materialized for performance)
CREATE TABLE user_feedback_stats (
    user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,

    -- Query satisfaction
    total_queries INTEGER NOT NULL DEFAULT 0,
    satisfied_queries INTEGER NOT NULL DEFAULT 0,

    -- Tag suggestions
    total_tag_suggestions INTEGER NOT NULL DEFAULT 0,
    accepted_tag_suggestions INTEGER NOT NULL DEFAULT 0,
    modified_tag_suggestions INTEGER NOT NULL DEFAULT 0,
    rejected_tag_suggestions INTEGER NOT NULL DEFAULT 0,

    -- Notifications
    total_notifications INTEGER NOT NULL DEFAULT 0,
    acted_notifications INTEGER NOT NULL DEFAULT 0,
    dismissed_notifications INTEGER NOT NULL DEFAULT 0,

    -- Computed rates
    query_satisfaction_rate NUMERIC(5,4) GENERATED ALWAYS AS (
        CASE WHEN total_queries > 0
             THEN satisfied_queries::numeric / total_queries
             ELSE 0 END
    ) STORED,
    tag_acceptance_rate NUMERIC(5,4) GENERATED ALWAYS AS (
        CASE WHEN total_tag_suggestions > 0
             THEN (accepted_tag_suggestions + modified_tag_suggestions)::numeric / total_tag_suggestions
             ELSE 0 END
    ) STORED,
    notification_action_rate NUMERIC(5,4) GENERATED ALWAYS AS (
        CASE WHEN total_notifications > 0
             THEN acted_notifications::numeric / total_notifications
             ELSE 0 END
    ) STORED,

    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Function to update feedback stats
CREATE OR REPLACE FUNCTION update_feedback_stats()
RETURNS TRIGGER AS $$
BEGIN
    -- Ensure user has a stats row
    INSERT INTO user_feedback_stats (user_id)
    VALUES (NEW.user_id)
    ON CONFLICT (user_id) DO NOTHING;

    -- Update based on feedback type
    IF NEW.feedback_type = 'query_satisfaction' THEN
        UPDATE user_feedback_stats
        SET total_queries = total_queries + 1,
            satisfied_queries = satisfied_queries + CASE WHEN NEW.action IN ('thumbs_up', 'accepted') OR NEW.rating >= 4 THEN 1 ELSE 0 END,
            updated_at = NOW()
        WHERE user_id = NEW.user_id;

    ELSIF NEW.feedback_type = 'tag_acceptance' THEN
        UPDATE user_feedback_stats
        SET total_tag_suggestions = total_tag_suggestions + 1,
            accepted_tag_suggestions = accepted_tag_suggestions + CASE WHEN NEW.action = 'accepted' THEN 1 ELSE 0 END,
            modified_tag_suggestions = modified_tag_suggestions + CASE WHEN NEW.action = 'modified' THEN 1 ELSE 0 END,
            rejected_tag_suggestions = rejected_tag_suggestions + CASE WHEN NEW.action = 'rejected' THEN 1 ELSE 0 END,
            updated_at = NOW()
        WHERE user_id = NEW.user_id;

    ELSIF NEW.feedback_type = 'notification_action' THEN
        UPDATE user_feedback_stats
        SET total_notifications = total_notifications + 1,
            acted_notifications = acted_notifications + CASE WHEN NEW.action = 'accepted' THEN 1 ELSE 0 END,
            dismissed_notifications = dismissed_notifications + CASE WHEN NEW.action = 'dismissed' THEN 1 ELSE 0 END,
            updated_at = NOW()
        WHERE user_id = NEW.user_id;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger for stats updates
CREATE TRIGGER trg_update_feedback_stats
AFTER INSERT ON user_feedback
FOR EACH ROW
EXECUTE FUNCTION update_feedback_stats();

-- Query session tracking (for satisfaction feedback)
CREATE TABLE query_sessions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    query_text TEXT NOT NULL,
    response_text TEXT,
    agents_used TEXT[],
    model_id VARCHAR(100),

    -- Timing
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    duration_ms INTEGER,

    -- Source
    source VARCHAR(50) NOT NULL DEFAULT 'api', -- 'api', 'voice', 'discord'

    -- Feedback link
    feedback_id UUID REFERENCES user_feedback(id)
);

CREATE INDEX idx_query_sessions_user ON query_sessions(user_id);
CREATE INDEX idx_query_sessions_started ON query_sessions(started_at);

COMMENT ON TABLE user_feedback IS 'Tracks user feedback for learning and agent improvement';
COMMENT ON TABLE user_feedback_stats IS 'Aggregated feedback statistics per user';
COMMENT ON TABLE query_sessions IS 'Tracks query sessions for satisfaction feedback';
