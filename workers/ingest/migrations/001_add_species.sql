-- Migration 001: add species column to existing D1 results table
-- Apply with: wrangler d1 execute opencurelabs --remote --file=workers/ingest/migrations/001_add_species.sql

ALTER TABLE results ADD COLUMN species TEXT NOT NULL DEFAULT 'human';

CREATE INDEX IF NOT EXISTS idx_results_species ON results(species);
