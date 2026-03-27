-- Add missing index for parent_result_id provenance lookups
-- (was documented but missing from schema)
CREATE INDEX IF NOT EXISTS idx_tasks_parent_result ON tasks (parent_result_id);
