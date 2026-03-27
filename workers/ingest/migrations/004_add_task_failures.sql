-- Migration 004: Add failure tracking columns to tasks table
ALTER TABLE tasks ADD COLUMN failure_reason TEXT;
ALTER TABLE tasks ADD COLUMN failed_at TEXT;
ALTER TABLE tasks ADD COLUMN failure_count INTEGER DEFAULT 0;
CREATE INDEX IF NOT EXISTS idx_tasks_failed ON tasks (status, failure_count);
