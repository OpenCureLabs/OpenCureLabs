# OpenCure Labs — Architecture Guide

## System Overview

OpenCure Labs is an autonomous AI-for-Science platform that runs computational
biology pipelines through specialist agents coordinated by NVIDIA NeMo Agent
Toolkit (AgentIQ). Results are reviewed by Claude Opus 4.6 (scientific critic) and
Grok (literature monitor), then published to GitHub, Discord, and PDF reports.

```
┌─────────────────────────────────────────────────────────────────────┐
│                         User / CLI                                  │
│   nat run --config coordinator/labclaw_workflow.yaml --input "..."  │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    NemoClaw (Coordinator)                            │
│              Gemini 2.0 Flash Lite — ReAct Agent                    │
│         Routes tasks to skills via NeMo AgentIQ                     │
└──────┬──────────┬──────────┬──────────┬──────────┬─────────────────┘
       │          │          │          │          │
       ▼          ▼          ▼          ▼          ▼
┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐
│Neoantigen│ │Structure │ │Molecular │ │  QSAR    │ │  Variant     │
│Prediction│ │Prediction│ │ Docking  │ │ Modeling │ │Pathogenicity │
│(MHCflurry│ │ (ESMFold │ │ (Vina /  │ │(RDKit +  │ │ (ClinVar +   │
│+pyensembl│ │AlphaFold)│ │  Gnina)  │ │  sklearn)│ │   CADD)      │
└──────┬───┘ └──────┬───┘ └──────┬───┘ └──────┬───┘ └──────┬───────┘
       │          │          │          │          │
       └──────────┴──────────┴──────────┴──────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                       Guardrails Layer                               │
│   output_validator  →  novelty_filter  →  safety_check              │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                    ┌──────────┴──────────┐
                    ▼                     ▼
          ┌──────────────┐      ┌──────────────────┐
          │ Claude Opus  │      │  Grok Reviewer   │
          │ (Anthropic)  │      │  (xAI API)       │
          │ Scientific   │      │  Literature       │
          │ Critique     │      │  Monitor          │
          └──────┬───────┘      └──────┬───────────┘
                 │                     │
                 └──────────┬──────────┘
                            ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        Publishers                                    │
│          GitHub  ←→  Discord  ←→  PDF Reports                       │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        PostgreSQL                                    │
│  agent_runs │ pipeline_runs │ experiment_results │ critique_log      │
│  discovered_sources                                                  │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Layered Architecture

The system is composed of three nested layers:

```
┌─────────────────────────────────────────────────────┐
│                   NemoClaw                           │
│  The running coordinator process — boots system,     │
│  manages sessions, routes tasks                      │
│                                                      │
│  ┌───────────────────────────────────────────────┐  │
│  │               LabClaw                          │  │
│  │  Scientific skill registry, domain logic,      │  │
│  │  guardrails, compute routing                   │  │
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
  creates a NeMo ReAct agent with Gemini as the reasoning LLM.
- **LabClaw** — the scientific plugin layer. Registers skills into NeMo's tool
  registry, enforces guardrails, routes compute to local GPU or Vast.ai.
- **NeMo AgentIQ** — the underlying orchestration framework. Provides YAML
  workflow definitions, the `nat` CLI, tool invocation, and telemetry.

---

## Agent Roles

| Agent | Role | LLM / Compute | Config |
|---|---|---|---|
| **NemoClaw** | Coordinator — task routing, session management | Gemini 2.0 Flash Lite (API) | `coordinator/labclaw_workflow.yaml` |
| **Cancer Agent** | Tumor immunology, neoantigen prediction | RTX 5070 (local) | `agents/cancer_agent.yaml` |
| **Rare Disease Agent** | Variant pathogenicity analysis | RTX 5070 (local) | `agents/rare_disease_agent.yaml` |
| **Drug Response Agent** | QSAR modeling + molecular docking | RTX 5070 / Vast.ai | `agents/drug_response_agent.yaml` |
| **Claude Opus 4.6** | Scientific critic — structured JSON critique | Anthropic API | `reviewer/claude_opus_config.yaml` |
| **Grok** | Literature reviewer + proactive dataset discovery | xAI API (Grok-3) | `reviewer/grok_config.yaml` |

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
| `DISCORD_WEBHOOK_URL` | No | Live agent logging to Discord |
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
│   ├── lab.sh           # tmux 6-pane launcher
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
| **Coordinator LLM** | Gemini 2.0 Flash Lite | Google AI API |
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
