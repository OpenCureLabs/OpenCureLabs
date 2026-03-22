-- Migration 002: Add species column to experiment_results
-- Run: psql -p 5433 -d opencurelabs -f db/migrations/002_add_species_to_experiment_results.sql

BEGIN;

ALTER TABLE experiment_results
  ADD COLUMN IF NOT EXISTS species TEXT NOT NULL DEFAULT 'human';

CREATE INDEX IF NOT EXISTS idx_experiment_results_species
  ON experiment_results(species);

-- Backfill from JSONB result_data where species was already stored
UPDATE experiment_results
  SET species = result_data->>'species'
  WHERE result_data->>'species' IS NOT NULL
    AND species = 'human'
    AND result_data->>'species' != 'human';

COMMIT;
