# OpenCure Labs — API Reference

## Package: agentiq_labclaw

**Version:** 0.1.0  
**Location:** `packages/agentiq_labclaw/agentiq_labclaw/`  
**Exports:** `LabClawSkill`, `labclaw_skill`

---

## Table of Contents

1. [Base Module](#base-module)
2. [Connectors](#connectors)
   - [TCGAConnector](#tcgaconnector)
   - [ChEMBLConnector](#chemblconnector)
   - [ClinVarConnector](#clinvarconnector)
3. [Guardrails](#guardrails)
   - [Output Validator](#output-validator)
   - [Novelty Filter](#novelty-filter)
   - [Safety Check](#safety-check)
4. [Publishers](#publishers)
   - [GitHubPublisher](#githubpublisher)
   - [PDFPublisher](#pdfpublisher)
5. [Database Layer](#database-layer)
   - [Connection Manager](#connection-manager)
   - [agent_runs](#agent_runs)
   - [pipeline_runs](#pipeline_runs)
   - [experiment_results](#experiment_results)
   - [critique_log](#critique_log)
   - [discovered_sources](#discovered_sources)
6. [Compute Layer](#compute-layer)
   - [Vast.ai Dispatcher](#vastai-dispatcher)
7. [NeMo AgentIQ Plugin](#nemo-agentiq-plugin)
8. [Dashboard](#dashboard)
9. [CLI Findings Tool](#cli-findings-tool)

---

## Base Module

**File:** `agentiq_labclaw/base.py`

### `LabClawSkill(ABC)`

Abstract base class for all scientific skills. See [SKILLS.md](SKILLS.md) for
full skill documentation.

### `labclaw_skill(**kwargs)` — Decorator

Registers a class into the global `_SKILL_REGISTRY`.

```python
@labclaw_skill(
    name="skill_name",
    description="...",
    input_schema=InputModel,
    output_schema=OutputModel,
    compute="local",      # or "vast_ai"
    gpu_required=False,
)
class MySkill(LabClawSkill):
    def run(self, input_data: InputModel) -> OutputModel:
        ...
```

### `get_skill(name: str) -> type[LabClawSkill] | None`

Returns the registered skill class, or `None` if not found.

### `list_skills() -> dict[str, type[LabClawSkill]]`

Returns the full skill registry as `{name: class}`.

---

## Connectors

Data connectors fetch information from external scientific databases. All
connectors are stateless classes with a configurable timeout.

### TCGAConnector

**File:** `agentiq_labclaw/connectors/tcga.py`  
**APIs:**
- GDC Data Portal: `https://api.gdc.cancer.gov`
- GEO/NCBI: `https://eutils.ncbi.nlm.nih.gov/entrez/eutils`

```python
from agentiq_labclaw.connectors.tcga import TCGAConnector

conn = TCGAConnector(timeout=30)
```

| Method | Parameters | Returns | Description |
|---|---|---|---|
| `query_cases` | `project_id: str`, `data_type: str = "Gene Expression Quantification"`, `size: int = 100` | `list[dict]` | Queries GDC `/files` endpoint for files in a TCGA project |
| `download_files` | `file_ids: list[str]`, `output_dir: str` | `list[str]` | Downloads files by GDC UUID to local directory |
| `query_geo` | `accession: str` | `dict` | Looks up a GEO accession via NCBI eutils |

---

### ChEMBLConnector

**File:** `agentiq_labclaw/connectors/chembl.py`  
**API:** `https://www.ebi.ac.uk/chembl/api/data`

```python
from agentiq_labclaw.connectors.chembl import ChEMBLConnector

conn = ChEMBLConnector(timeout=30)
```

| Method | Parameters | Returns | Description |
|---|---|---|---|
| `search_compound` | `smiles: str`, `similarity: int = 70` | `list[dict]` | Similarity search against ChEMBL by SMILES |
| `get_bioactivities` | `chembl_id: str`, `target: str \| None = None`, `limit: int = 100` | `list[dict]` | Fetches bioactivity data for a compound |
| `get_target_info` | `target_chembl_id: str` | `dict \| None` | Retrieves target metadata |

---

### ClinVarConnector

**File:** `agentiq_labclaw/connectors/clinvar.py`  
**API:** `https://eutils.ncbi.nlm.nih.gov/entrez/eutils`

```python
from agentiq_labclaw.connectors.clinvar import ClinVarConnector

conn = ClinVarConnector(timeout=30)
```

| Method | Parameters | Returns | Description |
|---|---|---|---|
| `lookup_variant` | `variant_id: str` | `dict \| None` | Looks up a variant in ClinVar (esearch → esummary) |
| `search_gene` | `gene_symbol: str`, `limit: int = 50` | `list[dict]` | Searches ClinVar for pathogenic variants in a gene |
| `lookup_omim` | `gene_symbol: str` | `list[dict]` | Queries MedGen for OMIM gene-disease associations |

---

## Guardrails

Guardrails enforce data quality and safety before results are published.

### Output Validator

**File:** `agentiq_labclaw/guardrails/output_validator.py`

```python
from agentiq_labclaw.guardrails.output_validator import validate_output

valid, error_msg = validate_output(output, OutputSchema)
```

| Function | Parameters | Returns |
|---|---|---|
| `validate_output` | `output: BaseModel`, `schema: type[BaseModel]` | `tuple[bool, str \| None]` |

Re-validates a Pydantic model by dumping and re-parsing. Returns `(True, None)`
on success, or `(False, error_message)` on validation failure.

---

### Novelty Filter

**File:** `agentiq_labclaw/guardrails/novelty_filter.py`

```python
from agentiq_labclaw.guardrails.novelty_filter import check_novelty

is_novel = check_novelty("neoantigen", {"gene": "TP53", ...})
```

| Function | Parameters | Returns |
|---|---|---|
| `check_novelty` | `result_type: str`, `result_data: dict` | `bool` |

Queries `experiment_results` table for matching prior results. Returns `True` if
no duplicates exist (novel finding).

---

### Safety Check

**File:** `agentiq_labclaw/guardrails/safety_check.py`

```python
from agentiq_labclaw.guardrails.safety_check import safety_check

safe, reason = safety_check(output, agent_run_id=42, critique_completed=True)
```

| Function | Parameters | Returns |
|---|---|---|
| `safety_check` | `output: BaseModel`, `agent_run_id: int \| None = None`, `critique_completed: bool = False` | `tuple[bool, str \| None]` |

Blocks publication if:
- No `agent_run_id` provided
- Confidence score < 0.1 (`MINIMUM_CONFIDENCE`)
- `critique_required=True` but `critique_completed=False`

---

## Publishers

Publishers deliver results to external systems.

### GitHubPublisher

**File:** `agentiq_labclaw/publishers/github_publisher.py`

```python
from agentiq_labclaw.publishers.github_publisher import GitHubPublisher

pub = GitHubPublisher(repo_path="/path/to/OpenCureLabs")
```

| Method | Parameters | Returns | Description |
|---|---|---|---|
| `commit_and_push` | `files: list[str]`, `message: str`, `branch: str = "main"` | `bool` | `git add` + `git commit -m` + `git push origin {branch}` |
| `commit_result` | `result_path: str`, `pipeline_name: str` | `bool` | Commits with message `"result: {pipeline_name} output"` |

---

### PDFPublisher

**File:** `agentiq_labclaw/publishers/pdf_publisher.py`

```python
from agentiq_labclaw.publishers.pdf_publisher import PDFPublisher

pub = PDFPublisher(output_dir="/path/to/OpenCureLabs/reports/")
path = pub.generate_report("Title", sections=[...], critique={...})
```

| Method | Parameters | Returns | Description |
|---|---|---|---|
| `generate_report` | `title: str`, `sections: list[dict]`, `critique: dict \| None = None` | `str` | Builds PDF with title, sections, optional critique. Returns file path. |

---

## Database Layer

**File:** `agentiq_labclaw/db/`  
See [DATABASE.md](DATABASE.md) for schema details.

### Connection Manager

**File:** `agentiq_labclaw/db/connection.py`  
**Environment:** `POSTGRES_URL` (default: `postgresql://localhost:5433/opencurelabs`)

```python
from agentiq_labclaw.db.connection import get_connection, close_connection

conn = get_connection()   # singleton, autocommit=True
close_connection()        # closes and clears
```

---

### agent_runs

**File:** `agentiq_labclaw/db/agent_runs.py`

| Function | Parameters | Returns | SQL |
|---|---|---|---|
| `start_run` | `agent_name: str` | `int` | `INSERT INTO agent_runs (agent_name, status) VALUES (%s, %s) RETURNING id` |
| `complete_run` | `run_id: int`, `status: str`, `result: dict \| None = None` | `None` | `UPDATE agent_runs SET completed_at = NOW(), status = %s, result_json = %s WHERE id = %s` |
| `get_run` | `run_id: int` | `dict \| None` | `SELECT ... FROM agent_runs WHERE id = %s` |

---

### pipeline_runs

**File:** `agentiq_labclaw/db/pipeline_runs.py`

| Function | Parameters | Returns | SQL |
|---|---|---|---|
| `start_pipeline` | `pipeline_name: str`, `input_data: dict \| None = None` | `int` | `INSERT INTO pipeline_runs (pipeline_name, input_data, status) ... RETURNING id` |
| `complete_pipeline` | `run_id: int`, `status: str`, `output_path: str \| None = None` | `None` | `UPDATE pipeline_runs SET status = %s, output_path = %s WHERE id = %s` |

---

### experiment_results

**File:** `agentiq_labclaw/db/experiment_results.py`

| Function | Parameters | Returns | SQL |
|---|---|---|---|
| `store_result` | `pipeline_run_id: int`, `result_type: str`, `result_data: dict`, `novel: bool = False` | `int` | `INSERT INTO experiment_results ... RETURNING id` |
| `check_novelty` | `result_type: str`, `result_data: dict` | `bool` | `SELECT COUNT(*) FROM experiment_results WHERE result_type = %s AND result_data = %s` |

---

### critique_log

**File:** `agentiq_labclaw/db/critique_log.py`

| Function | Parameters | Returns | SQL |
|---|---|---|---|
| `log_critique` | `run_id: int`, `reviewer: str`, `critique_json: dict` | `int` | `INSERT INTO critique_log (run_id, reviewer, critique_json) ... RETURNING id` |
| `get_critiques_for_run` | `run_id: int` | `list[dict]` | `SELECT ... FROM critique_log WHERE run_id = %s ORDER BY timestamp` |

---

### discovered_sources

**File:** `agentiq_labclaw/db/discovered_sources.py`

| Function | Parameters | Returns | SQL |
|---|---|---|---|
| `register_source` | `url: str`, `domain: str`, `discovered_by: str = "grok"`, `notes: str \| None = None` | `int` | `INSERT INTO discovered_sources ... RETURNING id` |
| `validate_source` | `source_id: int` | `None` | `UPDATE discovered_sources SET validated = TRUE WHERE id = %s` |
| `list_unvalidated` | — | `list[dict]` | `SELECT ... FROM discovered_sources WHERE validated = FALSE` |

---

## Compute Layer

### Shared Helpers

**File:** `agentiq_labclaw/compute/__init__.py`

Common utilities used by both the single-instance dispatcher and the batch pool
manager.

| Function | Parameters | Returns | Description |
|---|---|---|---|
| `resolve_wheel_url` | — | `str \| None` | Queries GitHub API for the latest `.whl` release asset. Supports private repos via `GITHUB_TOKEN`. Returns `None` if no wheel found. |
| `build_onstart_script` | `wheel_url: str \| None` | `str` | Generates the Vast.ai onstart bash script. Uses wheel URL if available, falls back to git clone. |
| `attach_ssh_key` | `instance_id: int` | `bool` | Reads `~/.ssh/xpclabs.pub` and POSTs it to `/instances/{id}/ssh/`. Required because account-level SSH keys are not automatically authorized on new instances. |

**Environment variables:**

| Variable | Default | Description |
|---|---|---|
| `VAST_AI_KEY` | — | Vast.ai API key (required) |
| `GITHUB_TOKEN` | — | GitHub token for private repo wheel downloads |
| `GITHUB_REPOSITORY` | `OpenCureLabs/OpenCureLabs` | Repo slug for wheel resolution. Set this if you forked the repo. |

**SSH key requirement:** OpenCure Labs expects an ed25519 key pair at
`~/.ssh/xpclabs` (private) and `~/.ssh/xpclabs.pub` (public). The public key
must be registered with your Vast.ai account (`vastai create ssh-key`) before
provisioning instances.

### Vast.ai Dispatcher

**File:** `agentiq_labclaw/compute/vast_dispatcher.py`  
**API:** `https://console.vast.ai/api/v0`  
**Environment:** `VAST_AI_KEY`

Handles GPU burst compute on Vast.ai when local GPU is unavailable.

#### `VastInstance` class

```python
instance = VastInstance(api_key="...", instance_id=12345)
```

| Method | Parameters | Returns | Description |
|---|---|---|---|
| `info` | — | `dict` | Property: GET `/instances/{id}/` |
| `wait_until_ready` | `timeout: int = 300`, `poll_interval: int = 10` | `dict` | Polls until `actual_status == "running"` |
| `destroy` | — | `None` | DELETE `/instances/{id}/` |

#### Module Functions

| Function | Parameters | Returns | Description |
|---|---|---|---|
| `_find_cheapest_offer` | `api_key: str`, `gpu_required: bool` | `dict` | Queries `/bundles/` for cheapest available offer |
| `_create_instance` | `api_key: str`, `offer_id: int`, `image: str = "pytorch/pytorch:latest"` | `int` | Provisions instance via `/asks/{offer_id}/`, attaches SSH key automatically |
| `dispatch` | `skill`, `input_data` | output model | Full lifecycle: find → provision → attach SSH → wait → SSH execute → parse → destroy (600s timeout) |

### Pool Manager (Batch Compute)

**File:** `agentiq_labclaw/compute/pool_manager.py`

Manages a fleet of Vast.ai instances for parallel batch workloads (Genesis
Mode). Provisions N instances, waits for all to be ready, then dispatches tasks
across the pool.

#### `PoolManager`

| Method | Parameters | Returns | Description |
|---|---|---|---|
| `__init__` | `target_size`, `gpu_required: bool = True`, `max_cost_hr: float = 0.40` | — | Sets fleet parameters |
| `scale_up` | — | `list[int]` | Resolves wheel URL once, provisions `target_size` instances in parallel, attaches SSH keys |
| `wait_for_ready` | `min_ready: int = 1`, `timeout: int = 900` | `list[int]` | Polls instances via SSH for `/tmp/labclaw_ready` marker |
| `get_ready_instances` | — | `list[int]` | Returns instance IDs that passed SSH readiness check |
| `teardown` | — | `None` | Destroys all provisioned instances |

### Batch Dispatch System

**Files:** `agentiq_labclaw/compute/batch_queue.py`,
`batch_dispatcher.py`, `worker.py`, `task_generator.py`

End-to-end batch pipeline for Genesis Mode (12+ tasks × 3 domains):

1. **task_generator.py** — Generates domain-specific research tasks
2. **batch_queue.py** — Thread-safe priority queue with status tracking
3. **worker.py** — Pulls tasks from queue, dispatches via SSH to pool instances
4. **batch_dispatcher.py** — Orchestrates: generate tasks → scale pool → dispatch
   workers → collect results → teardown

---

## NeMo AgentIQ Plugin

**File:** `agentiq_labclaw/nat_plugin.py`

Bridges LabClaw skills into NVIDIA NeMo Agent Toolkit (AgentIQ) workflows.

### `LabClawSkillConfig(FunctionBaseConfig)`

Registered as `"labclaw_skill"` in NeMo AgentIQ.

| Field | Type | Description |
|---|---|---|
| `skill_name` | `str` | Name of the LabClaw skill to invoke |

### `labclaw_skill_function(config, builder)`

Decorated with `@register_function(config_type=LabClawSkillConfig)`.

Yields a `FunctionInfo` with an inner `_run_skill(input_json: str) -> str`
closure that:
1. Looks up the skill by name via `get_skill()`
2. Deserializes input JSON into the skill's `input_schema`
3. Calls `skill.execute(input_data)`
4. Returns JSON output

Usage in YAML workflows:

```yaml
functions:
  neoantigen:
    _type: labclaw_skill
    skill_name: neoantigen_prediction
```

---

## Dashboard

### Web Dashboard

**File:** `dashboard/dashboard.py`  
**Framework:** FastAPI + Uvicorn  
**Default port:** 8787

```bash
cd /path/to/OpenCureLabs
python dashboard/dashboard.py --port 8787 --host 127.0.0.1
```

#### REST Endpoints

| Route | Method | Parameters | Returns |
|---|---|---|---|
| `/` | GET | — | HTML dashboard page |
| `/api/stats` | GET | — | `{"total_runs", "active_runs", "total_results", "novel_results", ...}` |
| `/api/findings` | GET | `novel_only: bool`, `limit: int` | `list[dict]` |
| `/api/runs` | GET | `limit: int` | `list[dict]` |
| `/api/critiques` | GET | `limit: int` | `list[dict]` |
| `/api/sources` | GET | `limit: int` | `list[dict]` |
| `/api/export/findings` | GET | `fmt: "json"\|"csv"`, `novel_only: bool`, `limit: int` | JSON or CSV download |
| `/api/export/critiques` | GET | `fmt: "json"\|"csv"`, `limit: int` | JSON or CSV download |

#### WebSocket

| Route | Protocol | Description |
|---|---|---|
| `/ws` | WebSocket | Real-time stats updates pushed every 5 seconds |

Message format:

```json
{"type": "stats", "data": {"total_runs": 42, ...}}
```

#### Shell Scripts

| Script | Purpose |
|---|---|
| `dashboard/lab.sh` | Starts dashboard + findings watcher in background |
| `dashboard/stop.sh` | Stops all dashboard processes |

---

## CLI Findings Tool

**File:** `dashboard/findings.py`

Terminal-based findings viewer with ANSI color output.

```bash
python dashboard/findings.py                # summary overview
python dashboard/findings.py --novel        # novel findings only
python dashboard/findings.py --agents       # recent agent runs
python dashboard/findings.py --critiques    # reviewer critiques
python dashboard/findings.py --sources      # discovered sources
python dashboard/findings.py --all          # everything
python dashboard/findings.py --watch        # live refresh every 10s
```

| Option | Description |
|---|---|
| `--novel` | Display all novel (non-replicated) findings in detail |
| `--agents` | Show last 20 agent runs |
| `--critiques` | Show last 10 critiques with score bars |
| `--sources` | Show last 20 discovered data sources |
| `--all` | Show all sections |
| `--watch` | Auto-refresh every 10 seconds |
