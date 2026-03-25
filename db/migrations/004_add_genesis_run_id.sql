-- Migration 004: Add genesis_run_id to batch_jobs and vast_spend
-- Run: psql -p 5433 -d opencurelabs -f db/migrations/004_add_genesis_run_id.sql
--
-- Tracks which Genesis run produced each job/spend record.
-- Format: "genesis-YYYYMMDD-HHMMSS" (matches log directory naming).
-- Enables per-run cost reporting and run history queries.

BEGIN;

-- ── batch_jobs ──────────────────────────────────────────────────────────────
ALTER TABLE batch_jobs
  ADD COLUMN IF NOT EXISTS genesis_run_id TEXT;

CREATE INDEX IF NOT EXISTS idx_batch_jobs_genesis_run_id
  ON batch_jobs(genesis_run_id);

-- ── vast_spend ──────────────────────────────────────────────────────────────
ALTER TABLE vast_spend
  ADD COLUMN IF NOT EXISTS genesis_run_id TEXT;

CREATE INDEX IF NOT EXISTS idx_vast_spend_genesis_run_id
  ON vast_spend(genesis_run_id);

-- ── llm_spend ───────────────────────────────────────────────────────────────
ALTER TABLE llm_spend
  ADD COLUMN IF NOT EXISTS genesis_run_id TEXT;

CREATE INDEX IF NOT EXISTS idx_llm_spend_genesis_run_id
  ON llm_spend(genesis_run_id);

COMMIT;
