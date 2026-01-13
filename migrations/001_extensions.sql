-- Migration: 001_extensions
-- Description: Enable required PostgreSQL extensions
-- Date: 2025-01

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";      -- UUID generation
CREATE EXTENSION IF NOT EXISTS "vector";          -- pgvector for similarity search
CREATE EXTENSION IF NOT EXISTS "postgis";         -- Geographic queries
CREATE EXTENSION IF NOT EXISTS "btree_gist";      -- Temporal range indexes
CREATE EXTENSION IF NOT EXISTS "pg_trgm";         -- Fuzzy text matching
