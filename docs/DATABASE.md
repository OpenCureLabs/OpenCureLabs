# OpenCure Labs — Database Reference

## Overview

OpenCure Labs uses **PostgreSQL 16** on port **5433** (non-standard to avoid
conflicts with other PostgreSQL instances). The database stores all agent
activity, pipeline results, scientific critiques, and discovered data sources.

- **Database name:** `opencurelabs`
- **Default connection:** `postgresql://localhost:5433/opencurelabs`
- **Environment variable:** `POSTGRES_URL`
- **Schema file:** `db/schema.sql`
- **DB abstraction layer:** `packages/agentiq_labclaw/agentiq_labclaw/db/`

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
│ status          │       │ timestamp        │       │ timestamp           │   │
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
| `timestamp` | `TIMESTAMP` | DEFAULT NOW() | When the result was stored |

**DB module:** `agentiq_labclaw.db.experiment_results`
- `store_result(pipeline_run_id, result_type, result_data, novel)` → returns `result_id`
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
