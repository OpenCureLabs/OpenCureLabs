-- OpenCure Labs PostgreSQL Schema
-- Database: opencurelabs
-- Run: sudo -u postgres psql -p 5433 -f db/schema.sql

CREATE DATABASE opencurelabs;
\c opencurelabs

CREATE TABLE IF NOT EXISTS agent_runs (
  id SERIAL PRIMARY KEY,
  agent_name TEXT NOT NULL,
  started_at TIMESTAMP DEFAULT NOW(),
  completed_at TIMESTAMP,
  status TEXT,
  result_json JSONB
);

CREATE TABLE IF NOT EXISTS discovered_sources (
  id SERIAL PRIMARY KEY,
  url TEXT,
  domain TEXT,
  discovered_by TEXT,
  discovered_at TIMESTAMP DEFAULT NOW(),
  validated BOOLEAN DEFAULT FALSE,
  notes TEXT
);

CREATE TABLE IF NOT EXISTS pipeline_runs (
  id SERIAL PRIMARY KEY,
  pipeline_name TEXT NOT NULL,
  input_data JSONB,
  output_path TEXT,
  started_at TIMESTAMP DEFAULT NOW(),
  status TEXT
);

CREATE TABLE IF NOT EXISTS critique_log (
  id SERIAL PRIMARY KEY,
  run_id INTEGER REFERENCES pipeline_runs(id),
  reviewer TEXT,
  critique_json JSONB,
  timestamp TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS experiment_results (
  id SERIAL PRIMARY KEY,
  pipeline_run_id INTEGER REFERENCES pipeline_runs(id),
  result_type TEXT,
  result_data JSONB,
  novel BOOLEAN DEFAULT FALSE,
  species TEXT NOT NULL DEFAULT 'human',
  status TEXT DEFAULT 'published',
  timestamp TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS llm_spend (
  id SERIAL PRIMARY KEY,
  provider TEXT NOT NULL,
  model TEXT,
  input_tokens INTEGER DEFAULT 0,
  output_tokens INTEGER DEFAULT 0,
  estimated_cost REAL DEFAULT 0,
  skill_name TEXT,
  agent_name TEXT,
  created_at TIMESTAMP DEFAULT NOW()
);

-- Performance indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_llm_spend_provider ON llm_spend(provider);
CREATE INDEX IF NOT EXISTS idx_llm_spend_created_at ON llm_spend(created_at);
CREATE INDEX IF NOT EXISTS idx_agent_runs_status ON agent_runs(status);
CREATE INDEX IF NOT EXISTS idx_agent_runs_started_at ON agent_runs(started_at);
CREATE INDEX IF NOT EXISTS idx_pipeline_runs_status ON pipeline_runs(status);
CREATE INDEX IF NOT EXISTS idx_pipeline_runs_started_at ON pipeline_runs(started_at);
CREATE INDEX IF NOT EXISTS idx_experiment_results_novel ON experiment_results(novel);
CREATE INDEX IF NOT EXISTS idx_experiment_results_species ON experiment_results(species);
CREATE INDEX IF NOT EXISTS idx_experiment_results_pipeline_run_id ON experiment_results(pipeline_run_id);
CREATE INDEX IF NOT EXISTS idx_experiment_results_timestamp ON experiment_results(timestamp);
CREATE INDEX IF NOT EXISTS idx_critique_log_run_id ON critique_log(run_id);
CREATE INDEX IF NOT EXISTS idx_critique_log_timestamp ON critique_log(timestamp);
CREATE INDEX IF NOT EXISTS idx_discovered_sources_validated ON discovered_sources(validated);

-- ── Batch dispatch tables ────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS batch_jobs (
  id           SERIAL PRIMARY KEY,
  batch_id     TEXT NOT NULL,
  skill_name   TEXT NOT NULL,
  input_data   JSONB NOT NULL,
  domain       TEXT,
  label        TEXT,
  priority     INTEGER DEFAULT 5,
  status       TEXT DEFAULT 'pending',
  instance_id  INTEGER,
  result_data  JSONB,
  error        TEXT,
  retry_count  INTEGER DEFAULT 0,
  created_at   TIMESTAMP DEFAULT NOW(),
  claimed_at   TIMESTAMP,
  started_at   TIMESTAMP,
  completed_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_batch_jobs_batch_status ON batch_jobs(batch_id, status);
CREATE INDEX IF NOT EXISTS idx_batch_jobs_status_priority ON batch_jobs(status, priority);

CREATE TABLE IF NOT EXISTS vast_pool (
  id           SERIAL PRIMARY KEY,
  instance_id  INTEGER UNIQUE NOT NULL,
  ssh_host     TEXT,
  ssh_port     INTEGER DEFAULT 22,
  gpu_name     TEXT,
  cost_per_hr  REAL,
  status       TEXT DEFAULT 'provisioning',
  jobs_done    INTEGER DEFAULT 0,
  created_at   TIMESTAMP DEFAULT NOW(),
  ready_at     TIMESTAMP,
  destroyed_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_vast_pool_status ON vast_pool(status);
CREATE INDEX IF NOT EXISTS idx_vast_pool_created_at ON vast_pool(created_at);
CREATE INDEX IF NOT EXISTS idx_batch_jobs_created_at ON batch_jobs(created_at);

-- ── Vast.ai spend tracking ──────────────────────────────────────────────────
-- Mirrors the dynamic CREATE TABLE in compute/vast_dispatcher.py so that a
-- fresh `psql -f db/schema.sql` install includes this table before migration
-- 004 runs ALTER TABLE against it.
CREATE TABLE IF NOT EXISTS vast_spend (
  id              SERIAL PRIMARY KEY,
  instance_id     INTEGER,
  skill_name      TEXT,
  gpu_name        TEXT,
  cost_per_hour   REAL,
  started_at      TIMESTAMP DEFAULT NOW(),
  ended_at        TIMESTAMP,
  total_cost      REAL DEFAULT 0,
  genesis_run_id  TEXT
);

CREATE INDEX IF NOT EXISTS idx_vast_spend_created_at ON vast_spend(started_at);
CREATE INDEX IF NOT EXISTS idx_vast_spend_instance_id ON vast_spend(instance_id);

-- Composite index for per-provider cost reports over time windows
CREATE INDEX IF NOT EXISTS idx_llm_spend_provider_created_at
  ON llm_spend(provider, created_at);
