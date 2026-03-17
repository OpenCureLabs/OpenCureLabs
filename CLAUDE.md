# CLAUDE.md — OpenCure Labs Agent Context

> Read this file at the start of every session. It is the operational context for
> all Claude Code agents working in this repository.

---

## Project Overview

OpenCure Labs is an autonomous AI-for-Science platform built on multi-agent
orchestration. It runs computational biology pipelines — genomics analysis,
protein structure prediction, molecular docking, QSAR modeling — through
specialist agents coordinated by NVIDIA NeMo Agent Toolkit (AgentIQ).

Results are reviewed by Claude Opus 4.6 (scientific critic) and Grok (literature
monitor), then published to GitHub, Discord, and PDF reports.

Full details: see README.md (source of truth — never overwrite it).
Architecture spec: see LABCLAW.md.

---

## Folder Structure

```
/root/xpc-labs/
├── agents/          # Specialist agent configs (cancer, rare-disease, drug-response)
├── coordinator/     # NemoClaw/LabClaw YAML workflows (NeMo AgentIQ)
├── skills/          # LabClaw scientific skill modules
├── pipelines/       # Genomics, docking, QSAR, structure prediction pipelines
├── data/            # Ingestion connectors (TCGA, GEO, ClinVar, ChEMBL)
├── reviewer/        # Claude Opus + Grok reviewer agent configs
├── reports/         # Generated PDF outputs
├── logs/            # Agent run logs (also streamed to Discord)
├── db/              # PostgreSQL schemas and migrations
├── config/          # NeMo configs, model settings
├── workspace/       # Grok's sandboxed working directory
├── docs/            # Wiki source files
├── .env             # API keys — NEVER commit this file
├── .gitignore       # Excludes .env, .venv, caches, etc.
├── README.md        # Source of truth — do not overwrite
├── LABCLAW.md       # LabClaw scientific skill layer spec
└── AGENT_INSTRUCTIONS.md  # Bootstrap playbook
```

---

## Key Conventions

1. **Always activate venv first:**
   ```bash
   source /root/xpc-labs/.venv/bin/activate
   ```

2. **Always work from /root/xpc-labs** — this is the project root.

3. **Grok agent runs from /root/xpc-labs/workspace/ only** — never from project root.

4. **Never commit .env** — API keys live on disk only, never in git. If .env is
   ever accidentally staged, run `git rm --cached .env` immediately and consider
   all keys compromised.

5. **Never overwrite README.md** — it is the source of truth for the project.

6. **All agent activity logs** to `logs/` directory and Discord webhook.

---

## Agent Roles

| Agent | Role | Compute |
|---|---|---|
| **NemoClaw** | Coordinator process — boots system, manages sessions | Local (Ollama) |
| **LabClaw** | Scientific skill layer — domain routing, guardrails | Local |
| **Cancer Agent** | Tumor immunology, neoantigen prediction | RTX 5070 |
| **Rare Disease Agent** | Variant pathogenicity analysis | RTX 5070 |
| **Drug Response Agent** | QSAR + molecular docking | RTX 5070 / Vast.ai |
| **Claude Opus 4.6** | Scientific critic — structured JSON critique | API |
| **Grok** | VM-resident researcher + literature reviewer | VM + xAI API |

---

## Running the Coordinator

```bash
source /root/xpc-labs/.venv/bin/activate
nat run --config_file coordinator/labclaw_workflow.yaml --input "your task here"
```

---

## PostgreSQL

- **Database:** `opencurelabs`
- **Connection:** `postgresql://localhost/opencurelabs` (local, no auth in dev)
- **Start service:** `service postgresql start`
- **Tables:** agent_runs, discovered_sources, pipeline_runs, critique_log, experiment_results

---

## Discord Logging

- Webhook URL read from `.env` as `DISCORD_WEBHOOK_URL`
- All agent reasoning traces and results stream to Discord in real time

---

## GitHub

- **Repo:** git@github.com:ShoneAnstey/OpenCureLabs.git
- **Remote:** SSH-based (no password commits)
- **Identity:** `agent@opencurelabs` / `OpenCure Labs Agent`
