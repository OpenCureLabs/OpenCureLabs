# OpenCure Labs — DevOps & Operations Guide

## Overview

This document covers the complete development, testing, deployment, and
operational infrastructure for OpenCure Labs: CI/CD pipelines, Codespaces
configuration, security scanning, testing, backup strategy, and the Zellij-based
lab session manager.

---

## Table of Contents

1. [Environment Setup](#environment-setup)
2. [CI/CD Pipeline](#cicd-pipeline)
3. [GitHub Codespaces](#github-codespaces)
4. [VS Code Tunnel](#vs-code-tunnel)
5. [Testing](#testing)
6. [Security Scanning](#security-scanning)
7. [Pre-Commit Hook](#pre-commit-hook)
8. [Lab Session Manager](#lab-session-manager)
9. [Dashboard](#dashboard)
10. [Backup Strategy](#backup-strategy)
11. [Dependency Management](#dependency-management)
12. [Git Configuration](#git-configuration)

---

## Environment Setup

### Quick Start

```bash
git clone git@github.com:OpenCureLabs/OpenCureLabs.git
cd OpenCureLabs
bash scripts/setup.sh
```

### Setup Script Steps (`scripts/setup.sh`)

| Step | Description | Skippable |
|---|---|---|
| Parse flags | `--skip-models` to skip heavy downloads | — |
| 1. System packages | python3, venv, pip, postgresql, fastp, openbabel, etc. | No |
| 2. Python venv | Creates `.venv` if missing | No |
| 3. Python deps | `nvidia-nat`, `requirements.txt`, `agentiq_labclaw` (editable) | No |
| 4. Scientific models | pyensembl release 110 (~500MB) + MHCflurry (~1GB) | Yes |
| 5. PostgreSQL | Start service, create DB, apply schema | No |
| 6. Environment | Create `.env` from `.env.example`, check API keys | No |
| 7. Pre-commit hook | Install security scanner hook | No |
| 8. Directories | Ensure all project dirs exist | No |
| 9. Verification | Import checks, CLI checks, DB connectivity | No |

### Required Environment Variables

| Variable | Source | Required | Purpose |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | `.env` | Yes | Claude Opus reviewer |
| `XAI_API_KEY` | `.env` | Yes | Grok agent |
| `GENAI_API_KEY` | `.env` | Yes | Gemini 2.0 Flash Lite (coordinator LLM) |
| `DISCORD_WEBHOOK_URL_AGENT_LOGS` | `.env` | No | Discord #agent-logs |
| `DISCORD_WEBHOOK_URL_RESULTS` | `.env` | No | Discord #results |
| `VAST_AI_KEY` | `.env` | No | Vast.ai GPU burst compute |
| `POSTGRES_URL` | `.env` or system | No | Default: `postgresql://localhost:5433/opencurelabs` |
| `LABCLAW_COMPUTE` | `.env` or system | No | `"local"` (default) or `"vast_ai"` |

---

## CI/CD Pipeline

**File:** `.github/workflows/ci.yml`  
**Triggers:** Push to `main`, pull requests to `main`

### Matrix

| Python | OS | PostgreSQL |
|---|---|---|
| 3.11 | ubuntu-latest | 16 |
| 3.12 | ubuntu-latest | 16 |

### Pipeline Steps

```
┌─────────────────────────────────────────────┐
│  1. Checkout code                           │
│  2. Set up Python (matrix: 3.11, 3.12)      │
│  3. Install dependencies                    │
│     pip install -r requirements.txt         │
│     pip install -e packages/agentiq_labclaw │
│  4. Apply database schema                   │
│     psql -f db/schema.sql                   │
│  5. Run tests                               │
│     pytest tests/ -v --tb=short             │
│  6. Lint (ruff) — always runs               │
│     ruff check packages/ pipelines/ dashboard/ │
│  7. Security scan (bandit) — always runs    │
│     bandit -r packages/agentiq_labclaw -q   │
└─────────────────────────────────────────────┘
```

### PostgreSQL Service Container

```yaml
services:
  postgres:
    image: postgres:16
    env:
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
      POSTGRES_DB: opencurelabs
    ports:
      - 5433:5432    # host:container
```

CI uses password auth: `POSTGRES_URL=postgresql://postgres:postgres@localhost:5433/opencurelabs`

---

## GitHub Codespaces

**File:** `.devcontainer/devcontainer.json`  
**Base image:** `mcr.microsoft.com/devcontainers/python:3.11`

### Features

| Feature | Purpose |
|---|---|
| `common-utils` | Standard dev utilities |
| `sshd` | SSH daemon for remote access |
| `postgresql-client` | psql CLI for database access |

### Post-Create Command

```bash
bash scripts/setup.sh --skip-models
```

Runs full setup except heavy model downloads (pyensembl + MHCflurry).

### Port Forwarding

| Port | Label | Behavior |
|---|---|---|
| 8787 | Dashboard | Notify on forward |
| 5433 | PostgreSQL | Silent forward |

### VS Code Extensions (auto-installed)

- `ms-python.python`
- `ms-python.vscode-pylance`
- `GitHub.copilot`
- `GitHub.copilot-chat`

---

## VS Code Tunnel

A persistent VS Code Tunnel named `opencure-wsl` runs as a systemd service on
the development VM, allowing browser-based access to the full development
environment.

### Access

```
https://vscode.dev/tunnel/opencure-wsl/root/opencurelabs
```

### Service Management

```bash
systemctl status code-tunnel    # check status
systemctl restart code-tunnel   # restart
```

---

## Testing

### Test Suite

**Location:** `tests/`  
**Framework:** pytest  
**Total tests:** 36

#### Test Files

| File | Tests | Description |
|---|---|---|
| `test_neoantigen.py` | 3 | Allele normalization, VCF parsing, full pipeline (conditional) |

#### Key Test: `test_neoantigen.py`

| Test | Skip Condition | What It Tests |
|---|---|---|
| `test_allele_normalization` | — | `_normalize_allele()` handles prefixed/unprefixed/case-insensitive alleles |
| `test_vcf_parsing` | — | Parses `data/synthetic_somatic.vcf`, verifies 2 variants (TP53 chr17, KRAS chr12) |
| `test_full_pipeline` | Skips if `~/.local/share/mhcflurry` missing | Full `NeoantigenSkill.run()` with 3 HLA alleles |

### Running Tests

```bash
source .venv/bin/activate

# All tests
pytest tests/ -v

# Specific test file
pytest tests/test_neoantigen.py -v

# With coverage
pytest tests/ --cov=packages/agentiq_labclaw --cov-report=term-missing
```

### Test Data

| File | Description |
|---|---|
| `tests/data/synthetic_somatic.vcf` | Synthetic VCF with TP53 and KRAS variants |

---

## Security Scanning

### Scanner

**File:** `security/security_scan.py`  
**Profile:** `security/profiles/opencurelabs.yaml`  
**Reports:** `security/reports/` (git-ignored)

### Tools Used

| Tool | Check | Severity Mapping |
|---|---|---|
| **ruff** | Code quality, style, imports | LOW–MEDIUM |
| **bandit** | Security-focused static analysis | MEDIUM–CRITICAL |
| **pip-audit** | Known CVEs in dependencies | HIGH–CRITICAL |
| **detect-secrets** | Hardcoded secrets, API keys | CRITICAL |

### Scan Profile (`security/profiles/opencurelabs.yaml`)

```yaml
name: opencurelabs
static:
  ruff_target: packages/agentiq_labclaw/
  bandit_target: packages/agentiq_labclaw/
  bandit_config: packages/agentiq_labclaw/pyproject.toml
  secrets_baseline: .secrets.baseline
```

### Grading System

| Grade | Criteria |
|---|---|
| A+ | 0 findings |
| A | LOW only |
| B | ≤5 MEDIUM, no HIGH/CRITICAL |
| C | >5 MEDIUM or ≤2 HIGH |
| D | >2 HIGH or 1 CRITICAL |
| F | >1 CRITICAL |

### Autofix Modes

| Mode | Behavior |
|---|---|
| `safe` | Fixes Tier 1 (ruff) automatically |
| `low` | Fixes LOW-severity only |
| `none` | Report only, no changes |

### CLI Usage

```bash
# Basic scan
python security/security_scan.py --profile security/profiles/opencurelabs.yaml

# Scan with safe autofix + Discord notification
python security/security_scan.py \
  --profile security/profiles/opencurelabs.yaml \
  --autofix safe \
  --discord

# Save baseline for drift detection
python security/security_scan.py \
  --profile security/profiles/opencurelabs.yaml \
  --baseline-save security/baseline.json

# Compare against baseline
python security/security_scan.py \
  --profile security/profiles/opencurelabs.yaml \
  --baseline-compare security/baseline.json
```

### Output

Reports are written to `security/reports/` as both Markdown and JSON:
- `scan-opencurelabs-{timestamp}.md` — human-readable report
- `scan-opencurelabs-{timestamp}.json` — machine-readable, CI-compatible

Exit code: **1** if CRITICAL or HIGH findings, **0** otherwise.

---

## Pre-Commit Hook

**File:** `security/pre-commit-hook.sh`

### Installation

```bash
cp security/pre-commit-hook.sh .git/hooks/pre-commit
chmod +x .git/hooks/pre-commit
```

Or automatically via `scripts/setup.sh` (Step 7).

### Behavior

1. Runs `security_scan.py` with `--autofix safe --discord`
2. **Pass** (grade A–C): commit proceeds
3. **Fail** (grade D–F): commit blocked with report reference
4. **Emergency bypass:** `git commit --no-verify` (not recommended)

---

## Lab Session Manager

### Starting the Lab

**File:** `dashboard/lab.sh`

```bash
bash dashboard/lab.sh
```

Creates a 6-pane Zellij session named `opencurelabs`:

```
┌──────────────┬──────────────┐
│ COORDINATOR  │    GROK      │
├──────────────┼──────────────┤
│    LOGS      │  POSTGRES    │
├──────────────┼──────────────┤
│  DASHBOARD   │   SHELL      │
└──────────────┴──────────────┘
```

| Pane | Purpose | Command |
|---|---|---|
| Coordinator | NeMo AgentIQ coordinator shell | venv activated |
| Grok | Grok agent workspace | `cd workspace/` |
| Logs | Real-time log viewer | `tail -f logs/*.log` |
| Postgres | DB activity monitor | `watch` on `agent_runs` |
| Dashboard | Terminal findings viewer | `findings.py --watch` |
| Shell | General-purpose shell | venv activated |

### Keyboard Shortcuts

Zellij uses a mode-based keybinding system with a discoverable status bar.
Common shortcuts:

| Shortcut | Action |
|---|---|
| `Ctrl+q` then `d` | Detach (session keeps running) |
| `Ctrl+p` then arrows | Switch pane focus |
| `Ctrl+p` then `f` | Toggle fullscreen (zoom) |
| `Ctrl+p` then `w` | Toggle floating pane |
| `Ctrl+n` | New pane |
| `Ctrl+t` | New tab |
| `Ctrl+s` then arrows | Scroll mode |
| `Alt f` | Findings popup (custom) |

### Stopping the Lab

**File:** `dashboard/stop.sh`

```bash
bash dashboard/stop.sh
```

1. Auto-commits uncommitted changes (`chore: auto-save on shutdown`)
2. Pushes to GitHub
3. Stops web dashboard
4. Kills Zellij session

---

## Dashboard

### Web Dashboard

```bash
python dashboard/dashboard.py --port 8787 --host 127.0.0.1
```

- **URL:** `http://localhost:8787`
- **Framework:** FastAPI + Uvicorn
- **WebSocket:** `ws://localhost:8787/ws` (real-time stats every 5s)
- **API docs:** `http://localhost:8787/docs` (auto-generated by FastAPI)

### CLI Findings Viewer

```bash
python dashboard/findings.py              # summary
python dashboard/findings.py --novel      # novel findings
python dashboard/findings.py --agents     # agent runs
python dashboard/findings.py --all        # everything
python dashboard/findings.py --watch      # live 10s refresh
```

---

## Backup Strategy

### Automated Backup

A daily backup script runs at **5:30 AM PST** (13:30 UTC) via cron.

**Script location:** `/root/backups/opencurelabs/backup.sh` (outside repo, not in git)

### What Gets Backed Up

| Item | Local Destination | Windows Mirror |
|---|---|---|
| PostgreSQL dump | `/root/backups/opencurelabs/db/` | `C:\Backups\OpenCureLabs\db\` |
| `.env` secrets | `/root/backups/opencurelabs/secrets/` | `C:\Backups\OpenCureLabs\secrets\` |
| WSL archive | `/root/backups/opencurelabs/archive/` | `C:\Backups\OpenCureLabs\archive\` |
| Repository | — | `C:\Backups\OpenCureLabs\repo\` |
| pyensembl models | — | `C:\Backups\OpenCureLabs\models\` |

### Retention Policy

| Type | Local | Windows |
|---|---|---|
| DB dumps | 14 days | 3 latest |
| Archives | 14 days | 3 latest |
| `.env` snapshots | — | 5 latest |

### Manual Backup/Restore

```bash
# Backup database
su - postgres -c "pg_dump -p 5433 -d opencurelabs -F c -Z 6" > backup.dump

# Restore database
su - postgres -c "pg_restore -p 5433 -d opencurelabs backup.dump"
```

---

## Dependency Management

### Python Dependencies

**Runtime:** `requirements.txt` (top-level)  
**Package:** `packages/agentiq_labclaw/pyproject.toml`

### Key Dependencies

| Category | Packages |
|---|---|
| **Core** | pydantic ≥2.0, psycopg2-binary ≥2.9, requests ≥2.28, pyyaml ≥6.0 |
| **ML/AI** | numpy ≥1.26, pandas ≥2.2, scikit-learn ≥1.4, pyarrow ≥17.0 |
| **Bioinformatics** | pysam ≥0.22, biopython ≥1.83, pyensembl ≥2.3, mhcflurry ≥2.1, rdkit ≥2024.3 |
| **LLM APIs** | anthropic ≥0.25, openai ≥1.20 |
| **NeMo AgentIQ** | nvidia-nat |
| **Web** | fastapi ≥0.110, uvicorn ≥0.29, reportlab ≥4.1 |
| **Dev/QA** | pytest ≥7.0, pytest-cov ≥4.0, ruff ≥0.4, bandit ≥1.7, pip-audit ≥2.7, detect-secrets ≥1.4 |

### Ruff Configuration

```toml
[tool.ruff]
target-version = "py311"
line-length = 120

[tool.ruff.lint]
select = ["E", "F", "W", "I", "S", "B", "UP"]
ignore = ["S101"]    # allow assert in tests
```

### Bandit Configuration

```toml
[tool.bandit]
exclude_dirs = ["tests"]
skips = ["B101"]     # ignore assert warnings
```

---

## Git Configuration

### Repository

- **Remote:** `git@github.com:OpenCureLabs/OpenCureLabs.git`
- **Auth:** SSH-based (no password)
- **Identity:** `agent@opencurelabs` / `OpenCure Labs Agent`
- **Branch:** `main`

### .gitignore

```
.env               # API keys — never commit
.venv/             # virtual environment
notes/             # local developer notes
__pycache__/       # Python bytecode
*.pyc / *.pyo      # compiled Python
*.egg-info/        # package metadata
data/raw/          # raw data downloads
logs/*.log         # runtime logs
db/data/           # PostgreSQL data dir
.DS_Store          # macOS metadata
*.swp              # vim swap files
security/reports/  # scan reports (ephemeral)
```

### Port Assignments

| Port | Service |
|---|---|
| 5433 | PostgreSQL |
| 8787 | Web Dashboard |
