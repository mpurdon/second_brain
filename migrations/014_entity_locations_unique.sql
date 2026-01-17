-- Add unique partial index for entity_locations
-- Required for ON CONFLICT clause to work properly

-- Drop the existing non-unique index first
DROP INDEX IF EXISTS idx_entity_locations_current;

-- Create unique partial index for current locations (valid_to IS NULL)
-- This allows ON CONFLICT (entity_id, label) WHERE valid_to IS NULL
CREATE UNIQUE INDEX idx_entity_locations_current_unique
ON entity_locations(entity_id, label)
WHERE valid_to IS NULL;
