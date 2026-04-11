# CLAUDE.md — OpenCure Labs Agent Context

> Read this file at the start of every session. It is the operational context for
> all Claude Code agents working in this repository.

---

## Project Overview

OpenCure Labs is an autonomous AI-for-Science platform built on multi-agent
orchestration. It runs computational biology pipelines — genomics analysis,
protein structure prediction, molecular docking, QSAR modeling — through
specialist agents coordinated by NVIDIA NeMo Agent Toolkit (AgentIQ).

Results are reviewed by Grok (scientific critic + literature monitor) through a
two-tier review process, then published to Cloudflare R2. PDF reports are
generated locally for auditing.

Full details: see README.md (source of truth — never overwrite it).
Architecture spec: see LABCLAW.md.

---

## Folder Structure

```
/root/opencurelabs/
├── agents/          # Specialist agent configs (cancer, rare-disease, drug-response)
├── coordinator/     # NemoClaw/LabClaw YAML workflows (NeMo AgentIQ)
├── skills/          # LabClaw scientific skill modules
├── pipelines/       # Genomics, docking, QSAR, structure prediction pipelines
├── data/            # Ingestion connectors (TCGA, GEO, ClinVar, ChEMBL)
├── reviewer/        # Grok reviewer agent (two-tier critique + literature)
├── reports/         # Generated PDF outputs
├── logs/            # Agent run logs
├── db/              # PostgreSQL schemas and migrations
├── config/          # NeMo configs, model settings
├── workspace/       # Grok's sandboxed working directory
├── docs/            # Wiki source files
├── .env             # API keys — NEVER commit this file
├── .gitignore       # Excludes .env, .venv, caches, etc.
├── README.md        # Source of truth — do not overwrite
└── LABCLAW.md       # LabClaw scientific skill layer spec
```

---

## Key Conventions

1. **Always activate venv first:**
   ```bash
   source /root/opencurelabs/.venv/bin/activate
   ```

2. **Always work from /root/opencurelabs** — this is the project root.

3. **Grok agent runs from /root/opencurelabs/workspace/ only** — never from project root.

4. **Never commit .env** — API keys live on disk only, never in git. If .env is
   ever accidentally staged, run `git rm --cached .env` immediately and consider
   all keys compromised.

5. **Never overwrite README.md wholesale** — it is the source of truth for the
   project. Targeted edits to keep it in sync with the codebase are expected.

6. **All agent activity logs** to `logs/` directory.

7. **Never use `git commit --no-verify`** — pre-commit hooks enforce security
   scanning and documentation checks. If a commit is blocked by the security
   scanner:
   - Read the report in `security/reports/` to understand the finding.
   - Fix the issue if possible (ruff auto-fix, update baseline for false
     positives, upgrade vulnerable dependency).
   - If the issue cannot be fixed (e.g. upstream CVE with no patch), notify the
     user with the finding details and ask for guidance.
   - **Never bypass the hook.** The security gate exists to prevent secrets,
     vulnerabilities, and lint regressions from entering the repository.

---

## Agent Roles

| Agent | Role | Compute |
|---|---|---|
| **NemoClaw** | Coordinator process — boots system, manages sessions | Gemini API |
| **LabClaw** | Scientific skill layer — domain routing, guardrails | Local |
| **Cancer Agent** | Tumor immunology, neoantigen prediction | RTX 5070 |
| **Rare Disease Agent** | Variant pathogenicity analysis | RTX 5070 |
| **Drug Response Agent** | QSAR + molecular docking | RTX 5070 / Vast.ai |
| **Grok** | Scientific critic (two-tier review) + researcher + literature monitor | VM + xAI API |

---

## Running the Coordinator

```bash
source /root/opencurelabs/.venv/bin/activate
nat run --config_file coordinator/labclaw_workflow.yaml --input "your task here"
```

---

## PostgreSQL

- **Database:** `opencurelabs`
- **Connection:** `postgresql://localhost/opencurelabs` (local, no auth in dev)
- **Start service:** `service postgresql start`
- **Tables:** agent_runs, discovered_sources, pipeline_runs, critique_log, experiment_results

---

## GitHub

- **Repo:** git@github.com:OpenCureLabs/OpenCureLabs.git
- **Remote:** SSH-based (no password commits)
- **Identity:** `agent@opencurelabs` / `OpenCure Labs Agent`
