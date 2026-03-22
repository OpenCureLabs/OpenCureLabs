# OpenCure Labs — Architecture Guide

## System Overview

OpenCure Labs is an autonomous AI-for-Science platform that runs computational
biology pipelines through specialist agents coordinated by NVIDIA NeMo Agent
Toolkit (AgentIQ). A hierarchical coordinator delegates tasks to domain-specific
specialist agents, each with curated skill subsets. Results pass through a
post-execution pipeline (guardrails → reviewers → publishers) before being
stored and published.

```
┌─────────────────────────────────────────────────────────────────────┐
│                         User / CLI                                  │
│   nat run --config coordinator/labclaw_workflow.yaml --input "..."  │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│              Hierarchical Coordinator (Gemini 2.5 Flash Lite)       │
│              Routes tasks to specialist agents + utility tools       │
│              Implemented in nat_specialists.py as LangGraph ReAct   │
└──────┬──────────────┬──────────────┬──────────────┬────────────────┘
       │              │              │              │
       ▼              ▼              ▼              ▼
┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│ Cancer Agent │ │ Rare Disease │ │ Drug Response│ │   Utility    │
│ (specialist) │ │   Agent      │ │   Agent      │ │   Tools      │
│              │ │ (specialist) │ │ (specialist) │ │              │
│ neoantigen   │ │ variant_path │ │ qsar         │ │ register_src │
│ structure    │ │ sequencing_qc│ │ mol_docking  │ │ report_gen   │
│ sequencing_qc│ │              │ │ structure    │ │ grok_research│
└──────┬───────┘ └──────┬───────┘ └──────┬───────┘ └──────┬───────┘
       │              │              │              │
       └──────────────┴──────────────┴──────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│              Post-Execution Orchestrator (orchestrator.py)           │
│                                                                      │
│   output_validator → novelty_filter → safety_check                  │
│         │                                                            │
│         ▼                                                            │
│   ┌─────────────┐  ┌──────────────────┐                             │
│   │ Claude Opus  │  │  Grok Reviewer   │  ← called for novel results│
│   │ (critique)   │  │  (literature)    │                             │
│   └──────┬───────┘  └──────┬───────────┘                             │
│          └─────────┬───────┘                                         │
│                    ▼                                                  │
│         ┌──────────────────────┐                                     │
│         │     Publishers       │                                     │
│         │  GitHub · PDF · R2   │                                    │
│         └──────────┬───────────┘                                     │
└────────────────────┼────────────────────────────────────────────────┘
                     ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     Storage & Publishing                             │
│  PostgreSQL: agent_runs · pipeline_runs · experiment_results        │
│  critique_log · discovered_sources                                   │
│                                                                      │
│  R2 (pub.opencurelabs.ai): results/{skill}/{date}/{uuid}.json       │
│  D1 (opencurelabs): results table — queryable via ingest Worker     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Layered Architecture

The system is composed of three nested layers:

```
┌─────────────────────────────────────────────────────┐
│                   NemoClaw                           │
│  The running coordinator process — boots system,     │
│  manages sessions, routes tasks to specialists       │
│                                                      │
│  ┌───────────────────────────────────────────────┐  │
│  │               LabClaw                          │  │
│  │  Scientific skill registry, domain logic,      │  │
│  │  guardrails, compute routing, orchestrator     │  │
│  │                                                │  │
│  │  ┌─────────────────────────────────────────┐  │  │
│  │  │     NVIDIA NeMo Agent Toolkit (AgentIQ)  │  │  │
│  │  │     YAML orchestration · nat CLI         │  │  │
│  │  │     tool registry · telemetry            │  │  │
│  │  └─────────────────────────────────────────┘  │  │
│  └───────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────┘
```

- **NemoClaw** — the coordinator process. Boots the system, loads YAML config,
  creates a hierarchical LangGraph ReAct agent with Gemini as the reasoning LLM.
  Delegates to domain-specialist agents instead of calling skills directly.
- **LabClaw** — the scientific plugin layer. Registers skills into NeMo's tool
  registry, enforces guardrails, routes compute to local GPU or Vast.ai, and
  runs the post-execution orchestrator (review + publish).
- **NeMo AgentIQ** — the underlying orchestration framework. Provides YAML
  workflow definitions, the `nat` CLI, tool invocation, and telemetry.

---

## Agent Roles

| Agent | Role | Type | LLM / Compute | Config |
|---|---|---|---|---|
| **Coordinator** | Hierarchical task routing to specialists | `hierarchical_coordinator` | Gemini 2.5 Flash Lite (API) | `coordinator/labclaw_workflow.yaml` |
| **Cancer Agent** | Tumor immunology, neoantigen prediction | `specialist_agent` | RTX 5070 (local) | `labclaw_workflow.yaml` → `cancer_agent` |
| **Rare Disease Agent** | Variant pathogenicity analysis | `specialist_agent` | RTX 5070 (local) | `labclaw_workflow.yaml` → `rare_disease_agent` |
| **Drug Response Agent** | QSAR modeling + molecular docking | `specialist_agent` | RTX 5070 / Vast.ai | `labclaw_workflow.yaml` → `drug_response_agent` |
| **Claude Opus 4.6** | Scientific critic — structured JSON critique | reviewer | Anthropic API | `reviewer/claude_opus_config.yaml` |
| **Grok** | Literature reviewer + dataset discovery | reviewer + skill | xAI API (Grok-3) | `reviewer/grok_config.yaml` |

### Coordinator → Specialist → Skill Mapping

```
Coordinator
├── cancer_agent
│   ├── neoantigen_prediction    (MHCflurry + pyensembl)
│   ├── structure_prediction     (ESMFold / AlphaFold DB)
│   └── sequencing_qc            (fastp)
├── rare_disease_agent
│   ├── variant_pathogenicity    (ClinVar + CADD)
│   └── sequencing_qc            (fastp)
├── drug_response_agent
│   ├── qsar                     (RDKit + sklearn)
│   ├── molecular_docking        (AutoDock Vina)
│   └── structure_prediction     (ESMFold / AlphaFold DB)
└── Utility tools (coordinator-level)
    ├── register_discovered_source
    ├── report_generator
    └── grok_research
```

Skills can be shared across agents (e.g., `structure_prediction` is used by both
the cancer and drug response agents). The coordinator decides which specialist to
invoke based on the task description.

---

## Adding Custom Agents

The platform is designed to scale. Adding a new specialist agent requires only
YAML configuration — no Python code changes.

### Step 1: Define the Agent in the Workflow YAML

Add a new block to `coordinator/labclaw_workflow.yaml`:

```yaml
  literature_researcher:
    _type: specialist_agent
    llm_name: coordinator_llm
    specialty_domain: literature_research
    system_prompt: >
      You are a literature research specialist for biomedical science.
      Your tools include dataset discovery and source registration.
      When given a task:
      1. Search for relevant datasets and publications
      2. Register newly discovered sources in the database
      3. Return structured findings with citations.
      Always use your tools — never fabricate results.
    tool_names:
      - grok_research
      - register_discovered_source
```

### Step 2: Register with the Coordinator

Add the agent name to the coordinator's `specialist_names` list:

```yaml
workflow:
  _type: hierarchical_coordinator
  specialist_names:
    - cancer_agent
    - rare_disease_agent
    - drug_response_agent
    - literature_researcher          # ← new
```

### Step 3: Update the Coordinator System Prompt (optional)

If you want the coordinator to know when to route to the new agent, update
`COORDINATOR_SYSTEM_PROMPT` in `nat_specialists.py` to describe the new agent's
domain. The coordinator will use this to decide which specialist handles each task.

### That's It

The `specialist_agent` config type is generic — it accepts any system prompt and
any subset of registered skills as tools. No Python code changes are needed
unless you're adding a new skill. NAT discovers the agent automatically from the
YAML.

### Example Agents You Could Add

| Agent | Domain | Skills (tool_names) |
|---|---|---|
| Literature Researcher | Proactive dataset/paper discovery | `grok_research`, `register_discovered_source` |
| Pharmacogenomics Agent | Drug-gene interaction analysis | `variant_pathogenicity`, `qsar` |
| Epigenetics Agent | Methylation/chromatin analysis | New skill needed |
| Clinical Trial Tracker | Trial registry monitoring | New connector + skill needed |
| Immunotherapy Agent | Checkpoint inhibitor response | `neoantigen_prediction`, `qsar` |

### Hierarchical Nesting

Agents can also be nested. Since specialist agents are just tools to the
coordinator, you can create a sub-coordinator that manages its own specialists:

```
Coordinator
├── genomics_coordinator        ← sub-coordinator (hierarchical_coordinator)
│   ├── cancer_agent
│   └── rare_disease_agent
├── drug_discovery_coordinator  ← sub-coordinator
│   ├── drug_response_agent
│   └── pharmacogenomics_agent
└── Utility tools
```

This is supported because LangGraph agents are composable — an agent's output is
just a string, so any agent can be wrapped as a tool for another agent.

---

## Scaling Constraints

| Factor | Practical Limit | Why | Mitigation |
|---|---|---|---|
| **Coordinator context window** | ~10-15 specialist agents | Each agent is a tool description the coordinator LLM must reason about. Beyond ~15, routing accuracy degrades. | Use hierarchical nesting (sub-coordinators) to keep each coordinator's tool count under 10. |
| **GPU** | 1 concurrent GPU job (local) | RTX 5070 runs one heavy workload at a time (docking, structure prediction). | Queue jobs sequentially, or burst to Vast.ai for parallel GPU compute. |
| **LLM API rate limits** | Per-provider | Each specialist agent makes its own LLM reasoning calls. More agents = more Gemini API calls per task. | Use Gemini Flash Lite (high rate limits, low cost). Batch tasks through fewer specialists when possible. |
| **LLM API cost** | Linear with agent count | Each specialist makes 2-5 LLM calls for ReAct reasoning per task delegation. | Share the same `coordinator_llm` across all specialists (already configured this way). |
| **External API rate limits** | ~1 req/sec (ChEMBL, ClinVar) | Connector APIs rate-limit clients. Multiple agents hitting the same API can trigger 429 errors. | Caching + exponential backoff on connectors (see Caching Strategy below). |
| **Memory** | ~500MB per specialist agent (in-process) | LangGraph agents hold their state in memory. | 128GB RAM on this machine supports ~50+ concurrent agents easily. |
| **PostgreSQL** | Thousands of concurrent agents | DB is not the bottleneck. Connection pooling handles scale. | Add indexes on commonly queried columns (novel, timestamp, status). |

### Serial vs. Parallel Execution

Currently, the coordinator dispatches to one specialist at a time (serial). For
tasks spanning multiple domains (e.g., "find drug candidates for this neoantigen
target"), the coordinator calls specialists sequentially.

**Future: Parallel dispatch.** Replace the sequential coordinator with a LangGraph
`StateGraph` that dispatches independent specialist calls in parallel:

```python
# Future parallel dispatch (not yet implemented)
graph = StateGraph(...)
graph.add_node("cancer", cancer_agent)
graph.add_node("drug", drug_response_agent)
graph.add_edge(START, "cancer")
graph.add_edge(START, "drug")  # parallel branch
graph.add_edge("cancer", "merge")
graph.add_edge("drug", "merge")
```

This would let the cancer agent and drug response agent run simultaneously when
their work is independent.

---

## Caching Strategy

### Current: In-Process Cache

API connectors (ChEMBL, ClinVar, TCGA) use Python's `functools.lru_cache` for
in-memory memoization. This eliminates duplicate API calls within the same agent
run.

```python
@functools.lru_cache(maxsize=256)
def fetch_compound(self, compound_id: str) -> dict:
    ...
```

Combined with exponential backoff on 429/503 responses:

```python
for attempt in range(max_retries):
    resp = requests.get(url)
    if resp.status_code == 429:
        wait = min(2 ** attempt, 60)
        retry_after = resp.headers.get("Retry-After")
        if retry_after:
            wait = int(retry_after)
        time.sleep(wait)
        continue
    return resp.json()
```

### Why `lru_cache` Is Sufficient (For Now)

NAT runs all agents **in a single Python process**. When the coordinator calls
the cancer agent, which calls neoantigen prediction, which calls the ClinVar
connector — all of that happens in the same process. One shared `lru_cache` covers
all agents, all skills, all connector calls within a pipeline run.

**When it's NOT sufficient:**

| Scenario | lru_cache works? | Upgrade path |
|---|---|---|
| Single `nat run` invocation | Yes | — |
| Multiple sequential `nat run` calls | No (cache resets between runs) | Add `requests-cache` for disk-backed caching |
| Vast.ai remote execution | No (separate machine) | Add Redis or shared disk cache on compute nodes |
| Multiple coordinator instances | No (separate processes) | Add Redis for cross-process cache |
| Cron-scheduled pipeline runs | No (new process each time) | Add `requests-cache` with SQLite backend |

### Upgrade Path: `requests-cache`

When you need persistence across runs, swap `lru_cache` for `requests-cache`
(zero-config SQLite-backed HTTP cache):

```python
import requests_cache
requests_cache.install_cache("labclaw_cache", expire_after=3600)
# All requests.get() calls are now cached to disk automatically
```

This is a drop-in replacement — no architecture changes needed. Install with
`pip install requests-cache`.

### Upgrade Path: Redis (Multi-Node)

For multi-node deployments (multiple Vast.ai instances, distributed agents),
use Redis as a shared cache backend:

```python
import requests_cache
requests_cache.install_cache(
    "labclaw_cache",
    backend="redis",
    connection=redis.Redis(host="cache-host"),
    expire_after=3600,
)
```

This requires a Redis instance but gives cross-process, cross-machine caching
with automatic TTL expiration.

---

## Data Flow

```
1. INGESTION
   TCGA/GEO ──→ TCGAConnector     ──┐
   ChEMBL   ──→ ChEMBLConnector   ──┤──→ Coordinator receives data
   ClinVar  ──→ ClinVarConnector  ──┤
   Grok     ──→ register_source    ──┘

2. PROCESSING
   Coordinator ──→ selects skill(s) ──→ LabClawSkill.execute()
                                        │
                                        ├── LABCLAW_COMPUTE=local → run locally
                                        └── LABCLAW_COMPUTE=vast_ai → VastDispatcher

3. VALIDATION
   Skill output ──→ output_validator (Pydantic schema check)
                ──→ novelty_filter (PostgreSQL dedup)
                ──→ safety_check (confidence, completeness)

4. REVIEW (novel results only)
   Novel result ──→ Claude Opus (scientific critique JSON)
                ──→ Grok (literature corroboration)
                ──→ critique_log table

5. PUBLISHING
   Validated result ──→ GitHub (commit + push)
                    ──→ Discord (webhook embed)
                    ──→ PDF report (ReportLab)

6. STORAGE
   All results ──→ PostgreSQL (experiment_results, pipeline_runs, agent_runs)
```

---

## Compute Routing

Each skill declares its compute target via the `@labclaw_skill` decorator.
LabClaw's `base.py` routes execution based on the `LABCLAW_COMPUTE` environment
variable:

- `LABCLAW_COMPUTE=local` (default) — runs on the local RTX 5070
- `LABCLAW_COMPUTE=vast_ai` — provisions a Vast.ai GPU instance, runs the job
  remotely via SSH, streams results back, and terminates the instance

The `opencure burst on/off/status` CLI command toggles compute mode and manages
Vast.ai instances.

---

## Communication Model

All inter-agent communication happens through NeMo's tool registry — everything
is a function call, not a network request. The coordinator calls skills as tools;
skills return Pydantic-validated output; guardrails validate before publishing.

Grok communicates back to LabClaw via the `register_discovered_source` skill —
when Grok finds a new dataset, it calls this skill to write to
`discovered_sources` in PostgreSQL and queue for coordinator review.

---

## Port Mappings

| Service | Port | Purpose |
|---|---|---|
| PostgreSQL | 5433 | Database (non-standard to avoid conflicts) |
| FastAPI Dashboard | 8787 | Web monitoring UI + WebSocket live updates |
| Gemini API | HTTPS | Coordinator LLM (external) |
| Anthropic API | HTTPS | Claude Opus reviewer (external) |
| xAI API | HTTPS | Grok reviewer/researcher (external) |

---

## Environment Variables

| Variable | Required | Purpose |
|---|---|---|
| `GENAI_API_KEY` | Yes | Gemini API — coordinator LLM |
| `ANTHROPIC_API_KEY` | Yes | Claude Opus 4.6 scientific reviewer |
| `XAI_API_KEY` | Yes | Grok researcher and literature monitor |
| `DISCORD_WEBHOOK_URL_AGENT_LOGS` | No | Agent trace logging to Discord #agent-logs |
| `DISCORD_WEBHOOK_URL_RESULTS` | No | Findings/results to Discord #results |
| `VAST_AI_KEY` | No | Burst GPU compute (Vast.ai) |
| `NVIDIA_API_KEY` | No | NIM endpoints (if needed) |
| `POSTGRES_URL` | No | Database connection (default: `postgresql://localhost:5433/opencurelabs`) |
| `LABCLAW_COMPUTE` | No | Compute mode: `local` (default) or `vast_ai` |

---

## Folder Structure

```
/root/opencurelabs/
├── agents/              # Specialist agent YAML configs
│   ├── cancer_agent.yaml
│   ├── rare_disease_agent.yaml
│   └── drug_response_agent.yaml
├── coordinator/         # NeMo AgentIQ workflow config
│   └── labclaw_workflow.yaml
├── packages/            # Python packages
│   └── agentiq_labclaw/ # LabClaw skill layer (see API-REFERENCE.md)
│       └── agentiq_labclaw/
│           ├── base.py          # Skill base class + registry
│           ├── cli.py           # opencure CLI (burst on/off)
│           ├── nat_plugin.py    # NeMo AgentIQ bridge
│           ├── compute/         # Vast.ai dispatcher
│           ├── connectors/      # TCGA, ChEMBL, ClinVar
│           ├── db/              # PostgreSQL abstraction layer
│           ├── guardrails/      # Output validation pipeline
│           ├── publishers/      # Discord, GitHub, PDF
│           └── skills/          # 8 scientific skill modules
├── pipelines/           # End-to-end pipeline runners
│   ├── run_pipeline.py  # CLI pipeline executor
│   └── eval_mode.py     # Evaluation/benchmark framework
├── dashboard/           # Monitoring tools
│   ├── dashboard.py     # FastAPI web dashboard (port 8787)
│   ├── findings.py      # CLI findings viewer
│   ├── lab.sh           # Zellij 6-pane launcher
│   └── stop.sh          # Graceful shutdown
├── reviewer/            # Reviewer agent configs + code
│   ├── claude_opus_config.yaml
│   ├── grok_config.yaml
│   ├── claude_reviewer.py
│   └── grok_reviewer.py
├── data/                # Data ingestion connectors
├── db/                  # PostgreSQL schemas
│   └── schema.sql
├── scripts/             # Setup and utility scripts
│   ├── setup.sh         # Full environment setup
│   └── tunnel-setup.sh  # VS Code Tunnel installer
├── security/            # Security scanning
│   ├── security_scan.py
│   ├── pre-commit-hook.sh
│   └── profiles/
├── tests/               # Test suite (pytest)
├── reports/             # Generated PDF outputs
├── logs/                # Agent run logs
├── workspace/           # Grok's sandboxed directory
├── config/              # Additional NeMo configs
├── docs/                # Documentation (this folder)
├── .github/workflows/   # CI pipeline
├── .devcontainer/       # GitHub Codespaces config
├── .env                 # API keys (never committed)
├── .env.example         # Template for .env
├── requirements.txt     # Python dependencies
├── pytest.ini           # Test configuration
├── README.md            # Source of truth (do not overwrite)
├── LABCLAW.md           # LabClaw specification
└── CLAUDE.md            # Agent operational context
```

---

## Technology Stack

| Layer | Technology | Version |
|---|---|---|
| **Language** | Python | 3.11+ |
| **Agent Framework** | NVIDIA NeMo Agent Toolkit (AgentIQ) | 1.5.0+ |
| **Agent Orchestration** | LangGraph + LangChain | 1.0+ |
| **Coordinator LLM** | Gemini 2.5 Flash Lite | Google AI API |
| **Scientific Reviewer** | Claude Opus 4.6 | Anthropic API |
| **Literature Reviewer** | Grok-3 | xAI API |
| **Database** | PostgreSQL | 16 |
| **Web Dashboard** | FastAPI + uvicorn | 0.110+ |
| **PDF Generation** | ReportLab | 4.1+ |
| **Genomics** | pysam, pyensembl, MHCflurry | various |
| **Cheminformatics** | RDKit, Open Babel | 2024.3+ |
| **ML** | scikit-learn | 1.4+ |
| **Data** | pandas, numpy, pyarrow | 2.2+, 1.26+, 17.0+ |
| **Docking** | AutoDock Vina / Gnina | external |
| **Structure Prediction** | ESMFold API / AlphaFold DB | external |
| **GPU Burst Compute** | Vast.ai API | on-demand |
| **CI/CD** | GitHub Actions | Python 3.11 + 3.12 matrix |
| **Dev Environment** | GitHub Codespaces | Python 3.11 devcontainer |
| **Security** | ruff, bandit, pip-audit, detect-secrets | various |
