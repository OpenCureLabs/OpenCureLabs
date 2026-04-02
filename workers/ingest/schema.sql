-- OpenCure Labs — D1 results index schema
-- Apply with: wrangler d1 execute opencurelabs --file=schema.sql

CREATE TABLE IF NOT EXISTS results (
    id              TEXT PRIMARY KEY,
    skill           TEXT NOT NULL,
    date            TEXT NOT NULL,           -- YYYY-MM-DD
    novel           INTEGER NOT NULL DEFAULT 0, -- 0/1 (SQLite bool)
    status          TEXT NOT NULL DEFAULT 'published',
    r2_url          TEXT NOT NULL,           -- public CDN URL to full object
    species         TEXT NOT NULL DEFAULT 'human', -- "human" | "dog" | "cat"
    confidence_score REAL,                  -- lightweight summary
    gene            TEXT,                   -- summary field (neoantigen / variant)
    contributor_id  TEXT,                   -- machine UUID, admin-only for moderation
    reviewed_at     TEXT,                   -- ISO 8601, set when critique posted
    created_at      TEXT NOT NULL           -- ISO 8601
);

CREATE INDEX IF NOT EXISTS idx_results_skill        ON results(skill);
CREATE INDEX IF NOT EXISTS idx_results_date         ON results(date);
CREATE INDEX IF NOT EXISTS idx_results_novel        ON results(novel);
CREATE INDEX IF NOT EXISTS idx_results_species      ON results(species);
CREATE INDEX IF NOT EXISTS idx_results_contributor  ON results(contributor_id);

-- ── Critiques ────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS critiques (
    id              TEXT PRIMARY KEY,
    result_id       TEXT NOT NULL REFERENCES results(id),
    reviewer        TEXT NOT NULL,           -- "claude_opus" | "grok_literature"
    overall_score   REAL,                    -- 0-10 aggregate
    recommendation  TEXT,                    -- "publish" | "revise" | "archive" | "reject"
    critique_data   TEXT NOT NULL,           -- JSON blob with dimensional scores
    r2_url          TEXT,                    -- public CDN URL to full critique
    created_at      TEXT NOT NULL            -- ISO 8601
);

CREATE INDEX IF NOT EXISTS idx_critiques_result_id  ON critiques(result_id);
CREATE INDEX IF NOT EXISTS idx_critiques_reviewer   ON critiques(reviewer);
