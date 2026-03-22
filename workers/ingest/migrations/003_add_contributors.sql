-- Migration 003: Add contributors table for Ed25519 public key registration
CREATE TABLE IF NOT EXISTS contributors (
    contributor_id  TEXT PRIMARY KEY,
    public_key      TEXT NOT NULL UNIQUE,
    status          TEXT NOT NULL DEFAULT 'active',  -- active | banned
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_contributors_status ON contributors(status);
