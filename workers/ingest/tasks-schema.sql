-- Central task queue for distributed research coordination
-- Apply via: wrangler d1 execute opencurelabs --file=tasks-schema.sql

CREATE TABLE IF NOT EXISTS tasks (
    id              TEXT PRIMARY KEY,
    skill           TEXT NOT NULL,
    input_hash      TEXT NOT NULL UNIQUE,
    input_data      TEXT NOT NULL,
    domain          TEXT,
    species         TEXT DEFAULT 'human',
    label           TEXT,
    priority        INTEGER DEFAULT 5,
    status          TEXT DEFAULT 'available',
    claimed_by      TEXT,
    claimed_at      TEXT,
    completed_at    TEXT,
    result_id       TEXT,
    created_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tasks_status_skill ON tasks (status, skill, priority);
CREATE INDEX IF NOT EXISTS idx_tasks_claimed_by ON tasks (claimed_by, status);
CREATE INDEX IF NOT EXISTS idx_tasks_domain ON tasks (domain, status);
