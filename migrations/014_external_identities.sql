-- Migration: 014_external_identities
-- Description: Add external identity columns for Discord, Alexa, etc.
-- Date: 2026-01

-- Add external identity columns to users table
ALTER TABLE users ADD COLUMN IF NOT EXISTS discord_id VARCHAR(255) UNIQUE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS alexa_user_id VARCHAR(255) UNIQUE;

-- Create indexes for external identity lookups
CREATE INDEX IF NOT EXISTS idx_users_discord_id ON users(discord_id) WHERE discord_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_users_alexa_user_id ON users(alexa_user_id) WHERE alexa_user_id IS NOT NULL;

-- Add comment explaining the columns
COMMENT ON COLUMN users.discord_id IS 'Discord user ID for linking Discord bot interactions';
COMMENT ON COLUMN users.alexa_user_id IS 'Alexa user ID for linking Alexa skill interactions';
