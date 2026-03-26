-- Dynamic task generation: track task provenance and pipeline chains
-- Apply via: wrangler d1 execute opencurelabs --file=workers/ingest/migrations/005_dynamic_tasks.sql

ALTER TABLE tasks ADD COLUMN source TEXT DEFAULT 'bank';
ALTER TABLE tasks ADD COLUMN parent_result_id TEXT;
ALTER TABLE tasks ADD COLUMN parent_task_id TEXT;
ALTER TABLE tasks ADD COLUMN chain_id TEXT;
ALTER TABLE tasks ADD COLUMN chain_step INTEGER DEFAULT 0;

CREATE INDEX IF NOT EXISTS idx_tasks_source ON tasks (source, status);
CREATE INDEX IF NOT EXISTS idx_tasks_chain ON tasks (chain_id, chain_step);
