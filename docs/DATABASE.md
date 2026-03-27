# OpenCure Labs — Database Reference

## Overview

OpenCure Labs uses **two database systems**:

1. **PostgreSQL 16** (local, port 5433) — stores agent activity, pipeline results,
   scientific critiques, and discovered data sources.
2. **Cloudflare D1** (remote, SQLite-compatible) — stores the central task queue,
   published results index, contributor registrations, and critiques for the
   distributed computing system.

### PostgreSQL

- **Database name:** `opencurelabs`
- **Default connection:** `postgresql://localhost:5433/opencurelabs`
- **Environment variable:** `POSTGRES_URL`
- **Schema file:** `db/schema.sql`
- **DB abstraction layer:** `packages/agentiq_labclaw/agentiq_labclaw/db/`

### Cloudflare D1

- **Database name:** `opencurelabs`
- **Schema file:** `workers/ingest/tasks-schema.sql`
- **Migrations:** `workers/ingest/migrations/`
- **Accessed via:** Cloudflare Worker at `ingest.opencurelabs.ai`

---

## Entity-Relationship Diagram

```
┌─────────────────┐
│   agent_runs     │
│─────────────────│
│ id (PK)         │
│ agent_name      │
│ started_at      │
│ completed_at    │
│ status          │
│ result_json     │
└─────────────────┘

┌─────────────────┐       ┌──────────────────┐       ┌─────────────────────┐
│ pipeline_runs    │       │  critique_log     │       │ experiment_results   │
│─────────────────│       │──────────────────│       │─────────────────────│
│ id (PK)         │──┐    │ id (PK)          │       │ id (PK)             │
│ pipeline_name   │  │    │ run_id (FK) ─────│───┐   │ pipeline_run_id (FK)│───┐
│ input_data      │  │    │ reviewer         │   │   │ result_type         │   │
│ output_path     │  └────│──────────────────│───┘   │ result_data         │   │
│ started_at      │       │ critique_json    │       │ novel               │   │
│ status          │       │ timestamp        │       │ synthetic           │   │
│                 │       │                  │       │ status              │   │
│                 │       │                  │       │ species             │   │
│                 │       │                  │       │ timestamp           │   │
└─────────────────┘       └──────────────────┘       └─────────────────────┘
        ▲                         ▲                           ▲
        │                         │                           │
        └─────────────────────────┴───────────────────────────┘
                    FK references pipeline_runs.id

┌──────────────────────┐
│  discovered_sources   │
│──────────────────────│
│ id (PK)              │
│ url                  │
│ domain               │
│ discovered_by        │
│ discovered_at        │
│ validated            │
│ notes                │
└──────────────────────┘
```

---

## Tables

### agent_runs

Tracks every agent execution — start, completion, status, and result payload.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `SERIAL` | PRIMARY KEY | Auto-incrementing run ID |
| `agent_name` | `TEXT` | NOT NULL | Agent identifier (e.g., `cancer_agent`, `coordinator`) |
| `started_at` | `TIMESTAMP` | DEFAULT NOW() | When the agent run began |
| `completed_at` | `TIMESTAMP` | nullable | When the agent run finished (NULL if still running) |
| `status` | `TEXT` | nullable | Run status: `running`, `completed`, `failed`, `cancelled` |
| `result_json` | `JSONB` | nullable | Full result payload as JSON |

**DB module:** `agentiq_labclaw.db.agent_runs`
- `start_run(agent_name)` → returns `run_id`
- `complete_run(run_id, status, result_json)` → updates completion time and status
- `get_run(run_id)` → returns full row

---

### pipeline_runs

Tracks multi-step pipeline executions with input/output metadata.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `SERIAL` | PRIMARY KEY | Auto-incrementing pipeline run ID |
| `pipeline_name` | `TEXT` | NOT NULL | Pipeline identifier (e.g., `neoantigen_discovery`) |
| `input_data` | `JSONB` | nullable | Input parameters as JSON |
| `output_path` | `TEXT` | nullable | Path to output file(s) |
| `started_at` | `TIMESTAMP` | DEFAULT NOW() | When the pipeline started |
| `status` | `TEXT` | nullable | Run status: `running`, `completed`, `failed` |

**DB module:** `agentiq_labclaw.db.pipeline_runs`
- `start_pipeline(pipeline_name, input_data)` → returns `pipeline_run_id`
- `complete_pipeline(pipeline_run_id, status, output_path)` → updates status

---

### experiment_results

Stores computed scientific results with novelty tracking for deduplication.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `SERIAL` | PRIMARY KEY | Auto-incrementing result ID |
| `pipeline_run_id` | `INTEGER` | FK → pipeline_runs(id) | Which pipeline produced this result |
| `result_type` | `TEXT` | nullable | Type of result (e.g., `neoantigen`, `variant`, `qsar`) |
| `result_data` | `JSONB` | nullable | Full result payload as JSON |
| `novel` | `BOOLEAN` | DEFAULT FALSE | Whether this is a novel (non-replicated) finding |
| `synthetic` | `BOOLEAN` | DEFAULT FALSE | Whether this result was generated from synthetic/demo data (not real experimental input). Synthetic results are stored for auditing but **never** published to R2, GitHub, or PDF reports. |
| `status` | `TEXT` | DEFAULT 'published' | Result lifecycle status: `published`, `blocked`, `synthetic` |
| `species` | `TEXT` | DEFAULT 'human' | Species: `human`, `dog`, `cat` |
| `timestamp` | `TIMESTAMP` | DEFAULT NOW() | When the result was stored |

**DB module:** `agentiq_labclaw.db.experiment_results`
- `store_result(pipeline_run_id, result_type, result_data, novel, status, synthetic)` → returns `result_id`
- `check_novelty(result_type, result_data)` → returns `bool` (True if no matching prior result)

---

### critique_log

Archives scientific critique JSON from the Grok reviewer (and historically from Claude Opus).

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `SERIAL` | PRIMARY KEY | Auto-incrementing critique ID |
| `run_id` | `INTEGER` | FK → pipeline_runs(id) | Which pipeline run is being critiqued |
| `reviewer` | `TEXT` | nullable | Reviewer identifier: `grok` (active) or `claude_opus` (historical) |
| `critique_json` | `JSONB` | nullable | Full critique payload (see Critique Schema below) |
| `timestamp` | `TIMESTAMP` | DEFAULT NOW() | When the critique was recorded |

**DB module:** `agentiq_labclaw.db.critique_log`
- `log_critique(run_id, reviewer, critique_json)` → returns `critique_id`
- `get_critiques_for_run(run_id)` → returns list of critique rows

#### Grok Critique Schema

```json
{
  "overall_score": 8.5,
  "dimensions": {
    "scientific_logic": 9,
    "statistical_validity": 8,
    "interpretive_accuracy": 8,
    "reproducibility": 9,
    "novelty_assessment": 8
  },
  "recommendation": "publish",
  "revision_notes": ["Consider expanding discussion of HLA coverage"]
}
```

#### Grok Literature Review Schema

```json
{
  "corroborating": [
    {"title": "...", "url": "...", "relevance": "high"}
  ],
  "contradicting": [],
  "related_work": [
    {"title": "...", "url": "...", "relevance": "medium"}
  ],
  "literature_score": 0.85,
  "confidence_in_finding": 0.9
}
```

---

### discovered_sources

Tracks datasets discovered by Grok's proactive research. Sources are registered
as unvalidated and queued for coordinator review.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `SERIAL` | PRIMARY KEY | Auto-incrementing source ID |
| `url` | `TEXT` | nullable | URL of the discovered dataset |
| `domain` | `TEXT` | nullable | Scientific domain (e.g., `genomics`, `proteomics`) |
| `discovered_by` | `TEXT` | nullable | Agent that found it (typically `grok`) |
| `discovered_at` | `TIMESTAMP` | DEFAULT NOW() | When the source was registered |
| `validated` | `BOOLEAN` | DEFAULT FALSE | Whether the coordinator has approved it |
| `notes` | `TEXT` | nullable | Description, relevance notes |

**DB module:** `agentiq_labclaw.db.discovered_sources`
- `register_source(url, domain, discovered_by, notes)` → returns `source_id`
- `validate_source(source_id)` → sets `validated=TRUE`
- `list_unvalidated()` → returns all unvalidated sources

---

## Connection Management

The `agentiq_labclaw.db.connection` module provides a singleton connection manager:

```python
from agentiq_labclaw.db import get_connection

conn = get_connection()  # Returns existing or creates new connection
# Uses POSTGRES_URL env var (default: postgresql://localhost:5433/opencurelabs)
```

All database interactions go through the `agentiq_labclaw.db` module — skills
never write to PostgreSQL directly.

---

## Setup & Administration

### Start PostgreSQL

```bash
service postgresql start
```

### Create Database

```bash
su - postgres -c "psql -p 5433 -c 'CREATE DATABASE opencurelabs;'"
```

### Apply Schema

```bash
su - postgres -c "psql -p 5433 -d opencurelabs -f db/schema.sql"
```

### Connect Interactively

```bash
su - postgres -c "psql -p 5433 -d opencurelabs"
```

### Useful Queries

```sql
-- Recent agent runs
SELECT agent_name, status, started_at, completed_at
FROM agent_runs ORDER BY started_at DESC LIMIT 10;

-- Novel findings
SELECT r.result_type, r.result_data, r.timestamp
FROM experiment_results r
WHERE r.novel = TRUE
ORDER BY r.timestamp DESC;

-- Critiques with scores
SELECT c.reviewer, c.critique_json->>'overall_score' AS score,
       c.critique_json->>'recommendation' AS recommendation,
       p.pipeline_name
FROM critique_log c
JOIN pipeline_runs p ON c.run_id = p.id
ORDER BY c.timestamp DESC;

-- Unvalidated data sources from Grok
SELECT url, domain, discovered_by, notes
FROM discovered_sources
WHERE validated = FALSE
ORDER BY discovered_at DESC;
```

### Backup & Restore

```bash
# Backup (custom format, compressed)
su - postgres -c "pg_dump -p 5433 -d opencurelabs -F c -Z 6" > backup.dump

# Restore (full)
su - postgres -c "pg_restore -p 5433 -d opencurelabs backup.dump"

# Restore (schema only)
su - postgres -c "pg_restore --schema-only -p 5433 -d opencurelabs backup.dump"

# Restore (data only)
su - postgres -c "pg_restore --data-only -p 5433 -d opencurelabs backup.dump"
```

The automated backup script at `/root/backups/opencurelabs/backup.sh` dumps the
database daily at 5:30 AM PST and mirrors to `C:\Backups\OpenCureLabs\db\`.

---

## Cloudflare D1 Tables

The D1 database powers the distributed computing system. It is accessed
exclusively through the Cloudflare Worker at `ingest.opencurelabs.ai` — no
direct SQL connections. Schema is defined in `workers/ingest/tasks-schema.sql`.

### tasks

The central task queue. Contains ~400K pre-generated research tasks plus
dynamically derived follow-up tasks.

| Column | Type | Default | Description |
|---|---|---|---|
| `id` | `TEXT` | PRIMARY KEY | UUID task identifier |
| `skill` | `TEXT` | NOT NULL | Skill name (e.g., `neoantigen_prediction`) |
| `input_hash` | `TEXT` | NOT NULL, UNIQUE | SHA-256 of canonical input JSON (dedup key) |
| `input_data` | `TEXT` | NOT NULL | Full input parameters as JSON |
| `domain` | `TEXT` | `''` | Research domain: `cancer`, `rare_disease`, `drug_response` |
| `species` | `TEXT` | `'human'` | Species: `human`, `dog`, `cat` |
| `label` | `TEXT` | `''` | Human-readable task label |
| `priority` | `INTEGER` | `10` | Priority (lower = higher): derived=2, tier1=3, tier2=5 |
| `status` | `TEXT` | `'available'` | Lifecycle: `available`, `claimed`, `completed`, `failed` |
| `claimed_by` | `TEXT` | NULL | Contributor ID who claimed the task |
| `claimed_at` | `TEXT` | NULL | ISO timestamp of claim |
| `completed_at` | `TEXT` | NULL | ISO timestamp of completion |
| `result_id` | `TEXT` | NULL | UUID of the submitted result |
| `failure_count` | `INTEGER` | `0` | Number of failed attempts (max 3) |
| `failure_reason` | `TEXT` | NULL | Most recent failure reason |
| `failed_at` | `TEXT` | NULL | Timestamp of last failure |
| `source` | `TEXT` | `'bank'` | Origin: `bank` (parameter bank), `derived` (chain), `discovery` (Grok) |
| `parent_result_id` | `TEXT` | NULL | Result ID that triggered this derived task |
| `parent_task_id` | `TEXT` | NULL | Task ID whose completion spawned this task |
| `chain_id` | `TEXT` | NULL | UUID grouping related pipeline tasks |
| `chain_step` | `INTEGER` | `0` | Step number within the chain (0–4) |
| `created_at` | `TEXT` | `datetime('now')` | Creation timestamp |

**Indexes:**
- `idx_tasks_status_skill` — `(status, skill, priority)` — claim query optimization
- `idx_tasks_claimed` — `(claimed_by)` — rate limiting lookups
- `idx_tasks_domain` — `(domain)` — domain filtering
- `idx_tasks_chain` — `(chain_id)` — chain lookups
- `idx_tasks_source` — `(source)` — source breakdown queries
- `idx_tasks_parent_result` — `(parent_result_id)` — provenance tracking

### results

Published scientific results, indexed for querying. Full result blobs are stored
in R2; this table holds the queryable metadata.

| Column | Type | Description |
|---|---|---|
| `id` | `TEXT` (PK) | UUID result identifier |
| `skill` | `TEXT` | Skill that produced this result |
| `date` | `TEXT` | Date of submission |
| `novel` | `INTEGER` | Whether the result is novel (1/0) |
| `status` | `TEXT` | `pending`, `published`, or `blocked` |
| `r2_url` | `TEXT` | URL to the full result blob in R2 |
| `species` | `TEXT` | Species |
| `confidence_score` | `REAL` | Skill-specific confidence metric |
| `gene` | `TEXT` | Gene symbol (if applicable) |
| `contributor_id` | `TEXT` | Contributing system's UUID |
| `created_at` | `TEXT` | Submission timestamp |

### contributors

Registered contributor public keys for Ed25519 signature verification.

| Column | Type | Description |
|---|---|---|
| `contributor_id` | `TEXT` (PK) | UUID contributor identifier |
| `public_key` | `TEXT` | Hex-encoded Ed25519 public key |
| `status` | `TEXT` | `active` or `suspended` |
| `created_at` | `TEXT` | Registration timestamp |

### critiques

Grok sweep verification results (Tier 2 review).

| Column | Type | Description |
|---|---|---|
| `id` | `TEXT` (PK) | UUID critique identifier |
| `result_id` | `TEXT` | Result being reviewed |
| `reviewer` | `TEXT` | Reviewer identifier (e.g., `grok-sweep`) |
| `critique_json` | `TEXT` | Full critique payload as JSON |
| `score` | `REAL` | Overall score (0–10) |
| `recommendation` | `TEXT` | `publish`, `block`, or `defer` |
| `created_at` | `TEXT` | Review timestamp |

### D1 Migrations

Migrations are in `workers/ingest/migrations/` and applied with:

```bash
npx wrangler d1 execute opencurelabs --remote --file=migrations/004_add_task_failures.sql
npx wrangler d1 execute opencurelabs --remote --file=migrations/005_dynamic_tasks.sql
```

| Migration | Purpose |
|---|---|
| `004_add_task_failures.sql` | Adds `failure_count`, `failure_reason`, `failed_at` columns |
| `005_dynamic_tasks.sql` | Adds `source`, `parent_result_id`, `parent_task_id`, `chain_id`, `chain_step` + indexes |
