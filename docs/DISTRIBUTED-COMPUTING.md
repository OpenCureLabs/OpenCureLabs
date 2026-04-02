# Distributed Computing — Central Task Queue

OpenCure Labs uses a BOINC-style central task queue for distributing research
work across GPU contributors. Instead of every contributor generating their own
tasks (and duplicating effort), a central queue on Cloudflare D1 coordinates who
works on what.

---

## How It Works

```
1. Admin populates queue    →  POST /tasks/generate (~400K deterministic tasks)
2. Contributor claims tasks →  GET /tasks/claim?count=5&contributor_id=alice
3. Contributor runs skills  →  Vast.ai GPU executes neoantigen/docking/QSAR/etc.
4. Contributor reports done →  POST /tasks/{id}/complete  (or /fail on error)
5. Worker derives tasks     →  High-confidence results auto-spawn follow-ups
6. Weekly cron reclaims     →  Tasks claimed >24h ago reset to "available"
```

---

## Quick Start (Contribute Mode)

```bash
# Clone and install
git clone https://github.com/OpenCureLabs/OpenCureLabs.git
cd OpenCureLabs
python3 -m venv .venv && source .venv/bin/activate
pip install -e packages/agentiq_labclaw

# Set credentials
export VAST_AI_KEY="your-vast-ai-key"
export OPENCURE_CONTRIBUTOR_ID="your-name-or-handle"

# Run 10 tasks, cap spending at $1.00
python -m agentiq_labclaw.compute.batch_dispatcher \
    --mode contribute --count 10 --max-cost 1.00

# Or run indefinitely until budget is exhausted
python -m agentiq_labclaw.compute.batch_dispatcher \
    --mode contribute --max-cost 5.00
```

The batch dispatcher will:
1. Provision a Vast.ai GPU instance (cheapest available)
2. Claim tasks from `https://ingest.opencurelabs.ai/tasks/claim`
3. Execute each skill on the remote GPU via SSH
4. Report completions back to the central queue
5. Tear down the instance when done (or on Ctrl+C)

---

## Task Types

The queue contains ~400K pre-generated research tasks across 5 scientific
skills:

| Skill | Count | Description | Example |
|---|---|---|---|
| `neoantigen_prediction` | ~397K | MHC binding analysis for tumor mutations | TP53 × breast × HLA-A*02:01 |
| `variant_pathogenicity` | ~224 | ClinVar/CADD pathogenicity scoring | CFTR (Cystic fibrosis) |
| `structure_prediction` | ~278 | Protein structure via ESMFold/AlphaFold | EGFR structure prediction |
| `molecular_docking` | ~285 | AutoDock Vina/GnINA/DiffDock binding affinity | EGFR × Erlotinib |
| `qsar` | ~162 | QSAR model training (RF/XGBoost/GNN) on ChEMBL | CHEMBL25 EGFR bioactivity |

Tasks span three domains: **cancer** (human + veterinary), **rare disease**,
and **drug response**.

### Parameter Banks

Tasks are generated deterministically from parameter banks defined in
`workers/ingest/tasks.ts`:

- **CANCER_GENES** — 227 genes (TP53, BRCA1, EGFR, KRAS, ...) — first 15 are tier 1 (priority 3), rest tier 2 (priority 5)
- **TUMOR_TYPES** — 35 TCGA codes (BRCA, LUAD, GBM, PAAD, AML, SCLC, ...)
- **HLA_PANELS** — 50 allele sets (global population coverage: European, East Asian, African, ...)
- **DRUG_TARGETS** — 95 target-compound pairs (kinase inhibitors, CDK, PI3K-mTOR, immune checkpoint, ...)
- **CHEMBL_DATASETS** — 55 ChEMBL assay datasets
- **RARE_DISEASE_VARIANTS** — 197 gene-disease pairs (lysosomal storage, metabolic, neurological, ...)
- **Veterinary** — canine (20 genes, 14 tumors, 10 DLA panels) and feline (12 genes, 10 tumors, 6 FLA panels)

---

## Deduplication

Duplicate work is prevented at two levels:

### 1. Task Deduplication (at generation)

Each task has an `input_hash` — the SHA-256 of its canonical input JSON. The D1
`tasks` table has a UNIQUE constraint on `input_hash`. When `POST /tasks/generate`
is called, it uses `INSERT OR IGNORE`, so re-running the generation inserts zero
rows for existing inputs.

### 2. Result Deduplication (at submission)

When a result is POSTed to `/results`, the ingest worker computes the same
`input_hash` from the result fields and checks for a matching completed task. If
found, it returns `409 Conflict` — preventing the same work unit from being
submitted twice.

---

## Claim Semantics

- **Atomic claims** — `UPDATE tasks SET status='claimed' WHERE status='available'
  LIMIT N` runs as a single D1 query. Two contributors claiming simultaneously
  will never get the same task.
- **Claim expiry** — Tasks claimed more than 24 hours ago are reset to
  `available` by the weekly cron trigger. This handles crashed contributors,
  network failures, or abandoned runs.
- **Skill filtering** — Contributors can claim tasks for a specific skill only:
  `GET /tasks/claim?skill=molecular_docking`
- **Batch claiming** — Request up to 50 tasks at once:
  `GET /tasks/claim?count=50`

---

## Rate Limiting

To prevent a single contributor from draining the queue, `GET /tasks/claim` is
rate-limited to **100 claims per 60 seconds** per `contributor_id`.

Exceeding this limit returns `429 Too Many Requests` with a `Retry-After` header
indicating how many seconds to wait. The batch dispatcher respects this automatically.

---

## Failure Reporting

When a task crashes mid-execution (CUDA OOM, timeout, invalid input, etc.),
contributors should report the failure:

```bash
curl -X POST https://ingest.opencurelabs.ai/tasks/{id}/fail \
  -H "Content-Type: application/json" \
  -d '{"reason": "CUDA out of memory on RTX 3060 (8GB VRAM)"}'
```

**Retry logic:** Failed tasks are automatically retried up to 3 times. On
failures 1–2, the task is reset to `available` for another contributor to claim.
After the 3rd failure, the task is permanently marked `failed`.

| Column | Description |
|---|---|
| `failure_count` | Number of times this task has failed (0–3) |
| `failure_reason` | Most recent failure reason string |
| `failed_at` | Timestamp of last failure |

---

## Dynamic Task Derivation

The task queue is not static. When a result exceeds confidence thresholds, the
ingest worker automatically spawns follow-up tasks — building a chain of
progressively deeper analysis.

### How It Works

1. Contributor completes a neoantigen prediction with confidence ≥ 0.7
2. The `POST /results` handler calls `deriveFollowUpTasks()`
3. New `structure_prediction` and `molecular_docking` tasks are auto-inserted
4. These derived tasks share a `chain_id` so you can track the full pipeline
5. When the structure prediction completes with confidence ≥ 0.6, a docking task
   is spawned at `chain_step: 2`

### Chain Rules

| Completed Skill | Confidence Needed | Auto-spawns |
|---|---|---|
| `neoantigen_prediction` | ≥ 0.7 | `structure_prediction` + `molecular_docking` |
| `structure_prediction` | ≥ 0.6 | `molecular_docking` |
| `molecular_docking` | affinity ≤ -8.0 | `qsar` |
| `variant_pathogenicity` | ≥ 0.7 | `structure_prediction` + `neoantigen_prediction` |

### Discovery-Driven Tasks

When Grok's `grok_research` skill finds new gene or drug targets in the
literature, `deriveDiscoveryTasks()` auto-spawns neoantigen and docking tasks
for those targets.

### Guardrails

- **Max chain depth:** 4 steps — prevents infinite cascading
- **Max derived tasks per result:** 20
- **Deduplication:** derived tasks use the same `input_hash` UNIQUE constraint
- **Priority:** Derived tasks get `priority: 2` (higher than bank tasks)
- **Source tracking:** `source` field is `"derived"` or `"discovery"`

### Visualizing Chains

The contribute dashboard at `https://opencurelabs.ai/contribute` shows active
pipeline chains with step-by-step visualization. The API also exposes:

- `GET /tasks/chains` — list 20 most recent chains
- `GET /tasks/chain/:chainId` — single chain detail with all tasks

---

## API Reference

All endpoints are on the ingest worker at `https://ingest.opencurelabs.ai`.

| Endpoint | Method | Auth | Description |
|---|---|---|---|
| `/tasks/claim` | GET | None | Claim available tasks (rate-limited: 100/60s) |
| `/tasks/:id/complete` | POST | None | Mark a task completed |
| `/tasks/:id/fail` | POST | None | Report task failure (3-retry logic) |
| `/tasks/stats` | GET | None | Queue statistics by status/skill/source |
| `/tasks/chains` | GET | None | List 20 most recent pipeline chains |
| `/tasks/chain/:chainId` | GET | None | Single chain detail with all tasks |
| `/leaderboard` | GET | None | Contributor rankings (top 50) |
| `/tasks/generate` | POST | `X-Admin-Key` | Populate queue (admin only, idempotent) |
| `/tasks/seed` | POST | `X-Admin-Key` | Seed tasks from external sources (max 500/req) |
| `/tasks/recycle` | POST | `X-Admin-Key` | Reset old completions to available |

See [API-REFERENCE.md](API-REFERENCE.md) for full request/response details.

---

## Cron Schedule

**Trigger:** `0 0 * * SUN` (every Sunday at midnight UTC)

The cron handler:
1. Calls `reclaimExpiredTasks()` — resets tasks stuck in `claimed` for >24h
2. Calls `populateTaskQueue()` — inserts any new tasks from parameter banks

This ensures the queue is always populated and stale claims don't block work.

### External Parameter Refresh

**Trigger:** systemd timer `opencurelabs-refresh.timer` — every Sunday at 01:00 UTC
(1 hour after the Worker cron)

The script `scripts/refresh_param_banks.py` queries public databases for entries
not in the hardcoded parameter banks and seeds new tasks via `POST /tasks/seed`:

| Source | What it fetches | Tasks generated |
|---|---|---|
| **ClinVar** (NCBI) | Pathogenic cancer-gene variants | neoantigen + structure + variant |
| **ChEMBL** (EBI) | Single-protein drug targets | QSAR (3 model types each) |
| **IMGT/HLA** (GitHub) | New HLA-A alleles | neoantigen combos with top genes |

Deduplication is server-side (`input_hash` UNIQUE constraint), so the script is
fully idempotent. Run manually with `--dry-run` to preview:

```bash
python scripts/refresh_param_banks.py --dry-run
python scripts/refresh_param_banks.py --sources clinvar,chembl
```

---

## D1 Schema

```sql
CREATE TABLE IF NOT EXISTS tasks (
  id               TEXT PRIMARY KEY,
  skill            TEXT NOT NULL,
  input_hash       TEXT NOT NULL UNIQUE,
  input_data       TEXT NOT NULL,           -- JSON
  domain           TEXT DEFAULT '',
  species          TEXT DEFAULT 'human',
  label            TEXT DEFAULT '',
  priority         INTEGER DEFAULT 10,
  status           TEXT DEFAULT 'available',
  claimed_by       TEXT,
  claimed_at       TEXT,
  completed_at     TEXT,
  result_id        TEXT,
  -- Failure tracking
  failure_count    INTEGER DEFAULT 0,
  failure_reason   TEXT,
  failed_at        TEXT,
  -- Dynamic derivation / chain tracking
  source           TEXT DEFAULT 'bank',     -- 'bank', 'derived', or 'discovery'
  parent_result_id TEXT,                    -- result that spawned this task
  parent_task_id   TEXT,                    -- task whose completion triggered derivation
  chain_id         TEXT,                    -- UUID grouping a pipeline chain
  chain_step       INTEGER DEFAULT 0,       -- step number within the chain (max 4)
  created_at       TEXT DEFAULT (datetime('now'))
);

CREATE INDEX idx_tasks_status_skill   ON tasks(status, skill, priority);
CREATE INDEX idx_tasks_claimed        ON tasks(claimed_by);
CREATE INDEX idx_tasks_domain         ON tasks(domain);
CREATE INDEX idx_tasks_chain          ON tasks(chain_id);
CREATE INDEX idx_tasks_source         ON tasks(source);
CREATE INDEX idx_tasks_parent_result  ON tasks(parent_result_id);
```

### Migrations

Migrations live in `workers/ingest/migrations/` and are applied with:

```bash
npx wrangler d1 execute opencurelabs --remote --file=migrations/004_add_task_failures.sql
npx wrangler d1 execute opencurelabs --remote --file=migrations/005_dynamic_tasks.sql
```

---

## Cost Estimate

| Component | Monthly Cost | Notes |
|---|---|---|
| D1 reads | ~$0.75 | 5M reads/month at $0.001/5K |
| D1 writes | ~$2.50 | 1M writes/month at $0.001/1K |
| Worker invocations | Free tier | <100K requests/day |
| R2 storage | ~$0.15/GB | Result blobs |
| **Total infrastructure** | **~$5/month** | For ~400K tasks + active contributors |

GPU compute cost is borne by each contributor via their own Vast.ai account.

---

## Adding New Tasks

To add new research tasks to the queue:

1. Edit `workers/ingest/tasks.ts` — add entries to the relevant parameter bank
   (e.g., add a gene to `CANCER_GENES`, a drug target to `DRUG_TARGETS`)
2. Deploy the worker: `cd workers/ingest && npx wrangler deploy`
3. Seed in chunks: `python scripts/seed_d1_queue.py` (calls `/tasks/generate`
   with `offset`/`limit` to avoid Worker CPU limits)
4. Only new tasks (with new `input_hash` values) will be inserted —
   regeneration is fully idempotent

---

## Architecture Diagram

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full system diagram showing how
the task queue fits into the overall OpenCure Labs pipeline.

The task queue sits alongside the existing result lifecycle:
- **Local mode** (`--mode local`, default) — generates its own tasks locally,
  no central coordination
- **Contribute mode** (`--mode contribute`) — claims from central queue,
  executes on Vast.ai, reports back

Both modes ultimately publish results through the same R2/D1 ingest pipeline
with Ed25519 signing and Grok two-tier review.

---

## Contribute Dashboard

A live dashboard is available at **https://opencurelabs.ai/contribute** showing:

- **Task stats** — available, claimed, completed, failed counts with auto-refresh
- **Skill breakdown** — tasks per skill with bar chart visualization
- **Active pipeline chains** — chain visualizations with step dots and status
- **Contributor leaderboard** — top 50 contributors ranked by tasks + results
- **Getting started guide** — setup instructions for new contributors

The dashboard fetches from `GET /tasks/stats`, `GET /leaderboard`, and
`GET /tasks/chains` with 30–60 second auto-refresh intervals.

### Contribute Mode Flow

In contribute mode, your coordinator machine handles all queue interaction while
Vast.ai GPU instances only execute the scientific skills:

```
Your machine (coordinator)              Vast.ai GPU instance
─────────────────────────               ────────────────────
batch_dispatcher                        Docker: labclaw-gpu:latest
  --mode contribute                       ↑
  │                                       │ SSH
  ├─ claim task from D1                   │
  ├─ ssh skill.run(task) ────────────────→│ execute neoantigen/docking/etc.
  ├─ receive result ←────────────────────│ return JSON
  └─ POST /tasks/{id}/complete            │
```

The Docker image (`ghcr.io/opencurelabs/labclaw-gpu:latest`) contains only the
skill execution code — it has no knowledge of D1- or the task queue. Task
sourcing, deduplication, and result reporting all happen on your coordinator.
This means changes to the queue (new tasks, new parameter banks) never require
rebuilding or redeploying the Docker image.
