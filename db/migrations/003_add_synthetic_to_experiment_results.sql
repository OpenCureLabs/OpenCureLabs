-- Migration 003: Add synthetic column to experiment_results
-- Run: psql -p 5433 -d opencurelabs -f db/migrations/003_add_synthetic_to_experiment_results.sql
--
-- Tracks whether a result was generated from synthetic/demo data
-- (e.g. synthetic VCF, synthetic QC metrics) vs real experimental data.
-- Synthetic results are stored for audit but NOT published to R2/GitHub.

BEGIN;

ALTER TABLE experiment_results
  ADD COLUMN IF NOT EXISTS synthetic BOOLEAN NOT NULL DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS idx_experiment_results_synthetic
  ON experiment_results(synthetic);

-- Backfill: mark known synthetic results from prior runs.
-- Synthetic results have result_data containing '"synthetic": true'
-- or sample_id patterns from the synthetic generator.
UPDATE experiment_results
  SET synthetic = TRUE
  WHERE (result_data->>'synthetic')::boolean = TRUE
    AND synthetic = FALSE;

COMMIT;
