-- Migration: 015_families_columns
-- Description: Add missing columns to families table
-- Date: 2026-01-19

-- Add description and created_by columns to families table
ALTER TABLE families ADD COLUMN IF NOT EXISTS description TEXT;
ALTER TABLE families ADD COLUMN IF NOT EXISTS created_by UUID REFERENCES users(id);

-- Backfill created_by from family_members (first admin)
UPDATE families f
SET created_by = (
    SELECT user_id FROM family_members fm
    WHERE fm.family_id = f.id AND fm.role = 'admin'
    ORDER BY fm.joined_at LIMIT 1
)
WHERE created_by IS NULL;
