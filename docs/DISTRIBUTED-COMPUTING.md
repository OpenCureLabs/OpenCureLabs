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
4. Contributor reports done →  POST /tasks/{id}/complete
5. Weekly cron reclaims     →  Tasks claimed >24h ago reset to "available"
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

## API Reference

All endpoints are on the ingest worker at `https://ingest.opencurelabs.ai`.

| Endpoint | Method | Auth | Description |
|---|---|---|---|
| `/tasks/claim` | GET | None | Claim available tasks |
| `/tasks/:id/complete` | POST | None | Mark a task completed |
| `/tasks/stats` | GET | None | Queue statistics by status/skill |
| `/tasks/generate` | POST | `X-Admin-Key` | Populate queue (admin only, idempotent) |

See [API-REFERENCE.md](API-REFERENCE.md) for full request/response details.

---

## Cron Schedule

**Trigger:** `0 0 * * SUN` (every Sunday at midnight UTC)

The cron handler:
1. Calls `reclaimExpiredTasks()` — resets tasks stuck in `claimed` for >24h
2. Calls `populateTaskQueue()` — inserts any new tasks from parameter banks

This ensures the queue is always populated and stale claims don't block work.

---

## D1 Schema

```sql
CREATE TABLE IF NOT EXISTS tasks (
  id          TEXT PRIMARY KEY,
  skill       TEXT NOT NULL,
  input_hash  TEXT NOT NULL UNIQUE,
  input_data  TEXT NOT NULL,     -- JSON
  domain      TEXT DEFAULT '',
  species     TEXT DEFAULT 'human',
  label       TEXT DEFAULT '',
  priority    INTEGER DEFAULT 10,
  status      TEXT DEFAULT 'available',
  claimed_by  TEXT,
  claimed_at  TEXT,
  completed_at TEXT,
  result_id   TEXT,
  created_at  TEXT DEFAULT (datetime('now'))
);

CREATE INDEX idx_tasks_status_skill ON tasks(status, skill, priority);
CREATE INDEX idx_tasks_claimed      ON tasks(claimed_by);
CREATE INDEX idx_tasks_domain       ON tasks(domain);
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
