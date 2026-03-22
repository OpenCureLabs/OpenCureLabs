-- Migration 002: Add critiques table and reviewed_at to results
-- Apply with: wrangler d1 execute opencurelabs --file=workers/ingest/migrations/002_add_critiques.sql

CREATE TABLE IF NOT EXISTS critiques (
    id              TEXT PRIMARY KEY,
    result_id       TEXT NOT NULL REFERENCES results(id),
    reviewer        TEXT NOT NULL,
    overall_score   REAL,
    recommendation  TEXT,
    critique_data   TEXT NOT NULL,
    r2_url          TEXT,
    created_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_critiques_result_id  ON critiques(result_id);
CREATE INDEX IF NOT EXISTS idx_critiques_reviewer   ON critiques(reviewer);

-- Track when a result was last reviewed
ALTER TABLE results ADD COLUMN reviewed_at TEXT;
