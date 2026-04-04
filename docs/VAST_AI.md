# Vast.ai GPU Compute Layer

> How OpenCure Labs dispatches scientific workloads to a fleet of cloud GPUs.

---

## Overview

The compute layer rents spot-market GPU instances from [Vast.ai](https://cloud.vast.ai/?ref_id=440482),
deploys the `agentiq_labclaw` package via Docker + pip, and executes research
skills (neoantigen prediction, molecular docking, QSAR modelling, etc.) in
parallel across the fleet. A PostgreSQL-backed job queue coordinates work, and a
pool manager handles instance lifecycle, health checks, and self-healing.

> **Note:** The Vast.ai link above is a referral link — credits help fund GPU compute for this open-science project.

Two execution modes are available:

| Mode | Description |
|------|-------------|
| **Batch** (`100`) | Provisions N instances, runs one batch of tasks, tears down |
| **Continuous** (`999`) | Provisions once, loops batch→monitor→batch until budget exhausted |

All GPU compute is orchestrated from `packages/agentiq_labclaw/agentiq_labclaw/compute/`.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Task Generator                                             │
│  Creates parameterized research tasks (skill + input data)  │
└────────────────────────────┬────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│  Batch Queue  (batch_queue.py)                              │
│  PostgreSQL FIFO with FOR UPDATE SKIP LOCKED claiming       │
│  Status: pending → running → done / failed                  │
│  Retries: up to 2 retries per job (3 total attempts)        │
└──────────────┬──────────────────────────────┬───────────────┘
               │                              │
               ▼                              ▼
┌──────────────────────────┐   ┌──────────────────────────────┐
│  Pool Manager            │   │  Workers (1 thread per GPU)  │
│  (pool_manager.py)       │   │  (worker.py)                 │
│  • Provision instances   │   │  • Claim jobs atomically     │
│  • Poll readiness        │   │  • Execute skills via SSH    │
│  • Health check / heal   │   │  • Report results to queue   │
│  • Auto-scale on demand  │   │  • Idle-poll between cycles  │
└──────────────────────────┘   └──────────────────────────────┘
               │                              │
               └──────────────┬───────────────┘
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  Vast.ai API  (vast_dispatcher.py + __init__.py)            │
│  • Offer search with reliability filtering                  │
│  • Instance provisioning (Docker image + onstart script)    │
│  • Budget / account balance tracking                        │
│  • SSH key attachment                                       │
└─────────────────────────────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────────────┐
│  Vast.ai Fleet                                              │
│  N GPU instances (RTX 5090/5080/5070 Ti/5060 Ti/etc.)      │
│  Each: Docker container + agentiq_labclaw wheel + SSH root  │
└─────────────────────────────────────────────────────────────┘
```

### Source Files

| File | Lines | Purpose |
|------|-------|---------|
| `pool_manager.py` | ~750 | Instance fleet management: provision, poll, heal, scale, teardown |
| `batch_dispatcher.py` | ~550 | Orchestration: `run_batch()` and `run_continuous()` entry points |
| `worker.py` | ~140 | Per-instance SSH job executor with idle-polling |
| `batch_queue.py` | ~340 | PostgreSQL job queue with atomic claiming |
| `vast_dispatcher.py` | ~250 | Budget tracking, Vast.ai API low-level calls |
| `__init__.py` | ~150 | Wheel resolution, onstart script generation, SSH key attachment |

---

## Configuration

### Environment Variables

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `VAST_AI_KEY` | Yes | — | Vast.ai API bearer token |
| `VAST_AI_BUDGET` | No | Account balance | Hard cap on total GPU spend ($) |
| `POSTGRES_URL` | No | `dbname=opencurelabs port=5433` | PostgreSQL connection |
| `LABCLAW_DOCKER_IMAGE` | No | `ghcr.io/opencurelabs/labclaw-gpu:latest` | Docker image for instances |
| `LABCLAW_IMAGE_LOGIN` | No | — | Private registry credentials (`user:token`) |
| `GITHUB_REPOSITORY` | No | `OpenCureLabs/OpenCureLabs` | Repo for wheel download |
| `GITHUB_TOKEN` | No | — | PAT for private repo wheel access (public repos don't need this) |

### CLI Options

```bash
python -m agentiq_labclaw.compute.batch_dispatcher \
  --count 100              # Tasks per batch
  --pool-size 10           # GPU instances to provision
  --max-cost 0.50          # Max $/hr per instance
  --domain cancer          # Skill domain filter (optional)
  --config tasks.yaml      # Custom task config (optional)
  --seed 42                # Reproducibility seed
  --image docker-url       # Override Docker image
  --continuous             # Enable continuous mode
  --budget 25.00           # Total $ budget (continuous)
  --cycles 10              # Max cycles (continuous, default: unlimited)
  --cooldown 5             # Seconds between cycles (default: 5)
  --dry-run                # Generate tasks only, don't dispatch
  --cleanup                # Clean up orphan pending jobs (>24h old) and exit
  --generate-only          # Submit tasks to queue without provisioning instances
  --drain-queue            # Drain existing pending jobs (skip task generation)
  --local-workers 2        # Run N local GPU worker threads (default: 0)
  --burst-threshold 50     # Defer Vast.ai until queue depth >= N (0 = always-on)
```

#### Queue-First Workflow

The `--generate-only` and `--drain-queue` flags decouple task generation from
execution, enabling a two-phase workflow:

```bash
# Phase 1: Fill the queue (no GPU spend)
python -m agentiq_labclaw.compute.batch_dispatcher --generate-only --count 200

# Phase 2: Drain locally (no cloud spend)
python -m agentiq_labclaw.compute.batch_dispatcher --drain-queue --local-workers 2

# Phase 2 (alt): Drain on Vast.ai
python -m agentiq_labclaw.compute.batch_dispatcher --drain-queue --pool-size 5
```

#### Burst Mode (Continuous)

With `--burst-threshold`, continuous mode starts with local workers only and
provisions Vast.ai instances on demand when the pending job count exceeds the
threshold. Cloud instances are torn down when the queue drains below
`threshold / 4`:

```bash
python -m agentiq_labclaw.compute.batch_dispatcher \
  --continuous --local-workers 2 --burst-threshold 50 --budget 10.00
```

Or via the dashboard TUI:

```bash
bash /root/opencurelabs/dashboard/run_research.sh
# → Genesis Mode → 999 — Continuous batch (Vast.ai pool)
```

---

## Instance Lifecycle

```
   ┌──────────────┐
   │ provisioning │  Vast.ai is pulling the Docker image and booting
   │  (0–8 min)   │  the container. No SSH access yet.
   └──────┬───────┘
          │  Vast.ai API: actual_status == "running"
          │  SSH host:port now available
          ▼
   ┌──────────────┐
   │    setup     │  Onstart script running: pip install, wheel download.
   │  (1–3 min)   │  SSH works but /tmp/labclaw_ready doesn't exist yet.
   └──────┬───────┘
          │  /tmp/labclaw_ready marker file exists
          ▼
   ┌──────────────┐
   │    ready     │  Instance idle, waiting to be assigned work.
   │              │  Worker thread will claim jobs for this instance.
   └──────┬───────┘
          │  Worker claims a job
          ▼
   ┌──────────────┐
   │    busy      │  Executing a skill via SSH.
   │              │  Returns to "ready" when job completes.
   └──────┬───────┘
          │  Health check fails / teardown / budget exhausted
          ▼
   ┌──────────────┐
   │  destroyed   │  Instance terminated on Vast.ai.
   └──────────────┘
```

### Readiness Detection

The pool manager uses two methods to detect readiness transitions:

1. **`poll_readiness()`** — Non-blocking, called every 10s during `_monitor_loop`.
   Polls the Vast.ai API for each provisioning instance; when `actual_status`
   becomes `"running"`, extracts `ssh_host` / `ssh_port` and transitions to
   `setup`. Then checks for `/tmp/labclaw_ready` via SSH to transition to `ready`.

2. **`wait_for_ready()`** — Blocking, used at startup. Same polling logic but
   blocks until `min_ready` instances are ready (or timeout at 30 min).

---

## Offer Selection & Reliability Filtering

When provisioning, `_find_offers()` queries the Vast.ai marketplace API:

```python
query = {
    "verified":      {"eq": True},       # Verified providers only
    "rentable":      {"eq": True},       # Currently available
    "disk_space":    {"gte": 20},        # ≥20 GB for Docker + work
    "inet_down":     {"gte": 100},       # ≥100 Mbps download
    "dph_total":     {"lte": max_cost},  # Cost cap (default $0.50/hr)
    "gpu_ram":       {"gte": 8},         # ≥8 GB VRAM
    "num_gpus":      {"gte": 1},         # At least one GPU
    "reliability2":  {"gte": 0.95},      # ≥95% historical uptime
}
```

Results are sorted by `dph_total` (cheapest first).

**Fallback:** If fewer than 20 offers are found at ≥95% reliability, the
threshold is relaxed to ≥90% and the search is retried. This ensures availability
on the spot market while still filtering out the worst hosts.

### Why Reliability Filtering Matters

Without it, Vast.ai returns machines that can't even boot:

- Hosts with broken DNS ("could not resolve host: cloud.vast.ai")
- Hosts with Docker build failures ("docker_build() error writing dockerfile")
- Machines that sit in "loading" state indefinitely

At `reliability2 >= 0.95`, these are filtered out. In our testing, this dropped
instance churn from ~80% to ~30%.

---

## Self-Healing & Health Checks

### `health_check()` — Called Between Cycles

```
1. Call poll_readiness() to advance any provisioning instances
2. For each active instance:
   ├─ If ready/busy/setup → SSH check with 3 retries (8s timeout, 5s gap)
   │   └─ Only mark dead if ALL 3 attempts fail (~39s total tolerance)
   └─ If provisioning for >8 minutes → query Vast.ai API
       └─ If status is "", "exited", "offline", "created", "loading" → mark dead
3. For each dead instance:
   ├─ Record spend to vast_spend table
   ├─ Destroy on Vast.ai API
   └─ Mark destroyed in DB
4. If active_count < target_size → scale_up() + wait_for_ready()
```

> **Note on SSH retries:** Vast.ai instances commonly lose SSH for 5–15 seconds
> after finishing heavy GPU work (GPU cooling cycle, SSH daemon briefly
> restarting, transient network blip). With a single 5-second SSH check, these
> normal blips were being misidentified as dead instances, destroying the pool
> after the first busy cycle. The 3-retry approach (each with 8s connect timeout,
> 5s between retries) gives an instance ~39 seconds to recover before it is
> declared dead and torn down.

### Stall Detection — In `_monitor_loop()`

If no jobs complete for 2 minutes (12 × 10s polling cycles):

1. Trigger `health_check()` to replace dead instances
2. Stop all workers and relaunch fresh ones
3. Reclaim any stale jobs (`running` > 1 min with no progress)
4. Reset stall counter

### Worker Lifecycle Management

Every 10s during monitoring:

- **Stop workers for destroyed instances** — prevents SSH to dead endpoints
- **Start workers for newly ready instances** — discovered by `poll_readiness()`

---

## Auto-Scaling

`auto_scale()` is called every 10s during batch monitoring:

- **Scale UP** when `pending_jobs > 2 × active_instances` and budget permits
- **Scale DOWN** only when `active_count > target_size` AND budget is nearly
  exhausted — the pool never shrinks below `target_size` during normal operation

This is important in continuous mode where a new batch is always imminent. Early
versions aggressively scaled down mid-batch when pending jobs dropped, killing
productive workers — this was fixed.

---

## Graceful Shutdown

When Ctrl+C is pressed during continuous mode:

1. SIGINT handler sets the `_shutdown` event
2. Current `_monitor_loop` / `wait()` notices and exits
3. `finally` block runs:
   - Suppresses additional SIGINT/SIGTERM (prevents double-kill during cleanup)
   - Stops all workers (`worker.stop()`)
   - Joins worker threads (10s timeout)
   - Calls `pool.teardown()` — destroys all instances, records spend
   - Marks all stale `running` agent_runs as `cancelled` in DB
4. Restores default signal handling

This prevents orphaned Vast.ai instances (which would keep billing) and ghost
"running" entries in the dashboard.

---

## Job Execution

Workers execute skills on remote instances via SSH:

```bash
ssh -i ~/.ssh/opencurelabs \
    -o StrictHostKeyChecking=no \
    -o ConnectTimeout=10 \
    -p $PORT root@$HOST \
    python3 -c '
import json, sys
from agentiq_labclaw.base import get_skill
Skill = get_skill("neoantigen_prediction")
s = Skill()
inp = Skill.input_schema.model_validate(json.loads(sys.stdin.read()))
result = s.run(inp)
print(json.dumps(result.model_dump(), default=str))
' <<< "$INPUT_JSON"
```

- Input is piped via stdin (avoids shell escaping)
- Output is captured from stdout as JSON
- Timeout: 10 minutes per job
- On failure: retry up to 2 times, then mark as failed

### Job Queue Claiming

Uses PostgreSQL `FOR UPDATE SKIP LOCKED` for lock-free atomic claiming:

```sql
UPDATE batch_jobs
SET status = 'running', instance_id = $1, claimed_at = NOW()
WHERE id = (
    SELECT id FROM batch_jobs
    WHERE status = 'pending'
    ORDER BY priority ASC, id ASC
    FOR UPDATE SKIP LOCKED
    LIMIT 1
)
RETURNING id, skill_name, input_data;
```

Multiple workers can claim simultaneously without conflicts — each gets a
different job.

---

## Database Tables

### `vast_pool` — Instance Fleet State

| Column | Type | Description |
|--------|------|-------------|
| `instance_id` | integer | Vast.ai contract ID (unique) |
| `ssh_host` | text | SSH hostname (populated when boot completes) |
| `ssh_port` | integer | SSH port (default 22) |
| `gpu_name` | text | GPU model (e.g., "RTX 5090") |
| `cost_per_hr` | real | Hourly rate in dollars |
| `status` | text | provisioning / setup / ready / busy / destroyed / failed |
| `jobs_done` | integer | Count of completed jobs on this instance |
| `created_at` | timestamp | When provisioned |
| `ready_at` | timestamp | When setup completed |
| `destroyed_at` | timestamp | When torn down |

### `batch_jobs` — Job Queue

| Column | Type | Description |
|--------|------|-------------|
| `batch_id` | text | Batch identifier (UUID hex, 12 chars) |
| `skill_name` | text | Skill module (e.g., "neoantigen_prediction") |
| `input_data` | jsonb | Serialised skill input |
| `status` | text | pending / running / done / failed |
| `instance_id` | integer | Vast.ai instance that claimed the job |
| `result_data` | jsonb | Skill output (on completion) |
| `retry_count` | integer | Attempts so far (max 2 retries) |
| `priority` | integer | Lower = higher priority |

### `vast_spend` — Cost Tracking

| Column | Type | Description |
|--------|------|-------------|
| `instance_id` | integer | Vast.ai reference |
| `gpu_name` | text | GPU type |
| `cost_per_hour` | real | Hourly rate |
| `started_at` | timestamp | Session start |
| `ended_at` | timestamp | Session end |
| `total_cost` | real | `(ended - started) / 3600 × cost_per_hour` |

---

## Docker Deployment

### Image

Default: `ghcr.io/opencurelabs/labclaw-gpu:latest` (private, requires
`LABCLAW_IMAGE_LOGIN`).

### Onstart Script

Runs automatically when the Docker container boots on Vast.ai:

1. Install Python dependencies (`pydantic`, `psycopg2-binary`, `requests`) if
   not already in the image
2. Install `agentiq_labclaw`:
   - **Fast path:** Download pre-built `.whl` from the latest GitHub release
   - **Fallback:** `pip install git+https://github.com/...` (slower)
3. Write `/tmp/labclaw_ready` marker file

The pool manager detects readiness by SSH-ing into the instance and checking
for the marker file.

### Wheel Resolution

`resolve_wheel_url()` queries the GitHub Releases API for the latest release of
the configured repository. It returns the download URL for the first `.whl`
asset found. For private repos, it uses the API asset URL (authenticated with
`GITHUB_TOKEN`); for public repos, it uses the direct `browser_download_url`.

---

## Operational Findings

Based on provisioning ~160 instances across multiple sessions:

### GPU Performance

| GPU | Instances | Jobs Done | Avg Lifespan | Notes |
|-----|-----------|-----------|--------------|-------|
| RTX 5090 | 30 | 76 | 9.1 min | Best absolute perf, most expensive |
| RTX 5080 | 37 | 26 | 8.4 min | Often fails to boot (low ready rate) |
| RTX 5070 Ti | 25 | 315 | 7.9 min | Best value — high throughput, reliable |
| RTX 5070 | 23 | 203 | 5.4 min | Good but shorter lifespans |
| RTX 5060 Ti | 18 | 281 | 8.5 min | Excellent — highest jobs/instance ratio |
| RTX 4070S Ti | 19 | 0 | 5.5 min | Never completed a job — avoid |
| RTX PRO 4500 | 5 | 26 | 12.7 min | Low availability, workstation GPU |
| RTX 4080S | 1 | 7 | 31.4 min | Rare availability, long-lived when found |

### Instance Reliability

| Metric | Value | Notes |
|--------|-------|-------|
| Total provisioned | 158 | All-time across all runs |
| Reached ready | 44 (27%) | Successfully booted + setup |
| Never ready | 114 (73%) | Failed to boot or killed during grace period |
| All-time spend | $3.20 | Across all instances |

**Key finding:** Most instance churn comes from three sources:

1. **Vast.ai host failures (~40%)** — Broken DNS, Docker build errors,
   machines stuck in "loading" forever. Mitigated by the `reliability2 >= 0.95`
   filter.

2. **Health check over-rotation (~30%)** — Earlier versions killed provisioning
   instances after only 1.5 minutes (before they could finish booting).
   Fixed by increasing the grace period to 8 minutes.

3. **Auto-scale over-aggression (~30%)** — `auto_scale()` used to scale down
   whenever `pending_jobs < active_instances - 2`, killing productive workers
   mid-batch. Fixed by never scaling below `target_size`.

### Bugs Found & Fixed

| Bug | Impact | Fix |
|-----|--------|-----|
| `scale_down()` killed most-productive workers first | Best instances destroyed first | Sort by `jobs_done` ascending (kill idle ones) |
| `auto_scale()` triggers scale-down mid-batch | Workers killed while new batch imminent | Never scale below `target_size` |
| Provisioning grace period too short (5 min) | Normal boot takes 3–8 min; healthy instances killed | Increased to 8 min |
| Ctrl+C doesn't clean up DB / instances | Ghost "running" agent_runs, orphan instances billing | `finally` block: suppress SIGINT, teardown, cancel stale runs |
| Workers using stale SSH endpoints | Jobs fail with `instance_id=NULL` after instance replaced | Stop workers for destroyed instances every 10s |
| `health_check` kills "created"/"loading" immediately | Normal Vast.ai boot states treated as dead | Only kill after grace period |
| Single SSH ping declares instance dead | Instances killed on transient 5-15s SSH hiccup after GPU work | SSH check now retries 3× (8s timeout, 5s gap) — 39s tolerance before destroy |

### Cost Efficiency

At current pricing ($0.10–0.50/hr per GPU), each research cycle of 20 tasks
costs approximately $0.05–0.15. Continuous mode with 10 instances can process
~100 tasks per hour at approximately $2–3/hr total fleet cost.

The RTX 5060 Ti offers the best cost/throughput ratio at ~$0.10–0.15/hr with
high job completion rates.

---

## Timeouts & Thresholds Reference

| Parameter | Value | Description |
|-----------|-------|-------------|
| Provisioning grace | 8 min | Don't kill booting instances before this |
| Setup wait timeout | 30 min | Max time to wait for first instance ready |
| SSH connect timeout | 10 sec | SSH connection establishment (job execution) |
| SSH alive check — connect timeout | 8 sec | Per-attempt timeout for health check SSH ping |
| SSH alive check — retries | 3× | Attempts before instance declared dead |
| SSH alive check — total tolerance | ~39 sec | Must be unresponsive this long to be destroyed |
| Remote job timeout | 10 min | Max execution time per skill |
| Worker idle timeout | 2 min | How long workers wait for new batches |
| Stall detection | 2 min | No-progress threshold before health check |
| Monitor poll interval | 10 sec | How often `_monitor_loop` checks status |
| Job claim poll | 5 sec | Worker idle-polling frequency |
| Stale job reclaim | 15 min | Running jobs with no heartbeat get requeued |
| Max retries | 2 | Failed jobs get requeued up to 2 times |
| Reliability threshold | ≥95% | Vast.ai host uptime filter (falls back to 90%) |
| Cooldown between cycles | 5 sec | Pause between continuous batch cycles |
