-- XPC Labs PostgreSQL Schema
-- Database: xpclabs
-- Run: sudo -u postgres psql -p 5433 -f db/schema.sql

CREATE DATABASE xpclabs;
\c xpclabs

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
  timestamp TIMESTAMP DEFAULT NOW()
);
