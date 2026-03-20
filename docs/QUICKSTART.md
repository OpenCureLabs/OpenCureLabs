# Quickstart Guide

This guide takes you from a **fresh Ubuntu machine** to a **running OpenCure Labs
platform** with all agents, pipelines, and the Zellij control panel.

**Time required:** ~20 minutes (plus model download time on your connection)
**Disk space:** ~5 GB (Python packages, scientific models)

---

## Option A: Automated Setup (Recommended)

```bash
# Clone the repo
git clone https://github.com/OpenCureLabs/OpenCureLabs.git
cd OpenCureLabs

# Run the setup script (installs everything)
sudo bash scripts/setup.sh

# Edit your API keys
nano .env

# Launch the control panel
bash dashboard/lab.sh
```

The setup script handles system packages, Python venv, scientific models,
PostgreSQL, and verification. See [What the Setup Script Does](#what-the-setup-script-does)
below for details.

---

## Option B: Manual Setup

If you prefer to understand each step, or the automated setup doesn't work for
your environment, follow this section.

### 1. System Packages

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y \
  python3 python3-venv python3-pip python3-dev \
  build-essential git curl wget tmux htop zellij \
  postgresql postgresql-contrib libpq-dev
```

### 2. Python Environment

```bash
cd /path/to/OpenCureLabs

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install all dependencies
pip install --upgrade pip
pip install -r requirements.txt

# Install the LabClaw package (editable mode)
pip install -e packages/agentiq_labclaw
```

### 3. Scientific Models

The neoantigen pipeline requires genome annotation data and MHC binding models.
These are large downloads (~1.5 GB total).

```bash
source .venv/bin/activate

# Ensembl human genome annotation (release 110)
pyensembl install --release 110 --species human

# MHCflurry binding prediction models
mhcflurry-downloads fetch models_class1 models_class1_pan models_class1_presentation
```

### 4. PostgreSQL

OpenCure Labs uses PostgreSQL (port **5433**) for persistent state — agent runs,
pipeline results, discovered sources.

```bash
# Start PostgreSQL
sudo service postgresql start

# Check which port it's on
sudo -u postgres psql -c "SHOW port;"

# If it's on 5432 and you need 5433, edit the config:
# sudo nano /etc/postgresql/*/main/postgresql.conf
# Change: port = 5433
# Then: sudo service postgresql restart

# Create the database
sudo -u postgres psql -p 5433 -c "CREATE DATABASE opencurelabs;"

# Apply the schema
sudo -u postgres psql -p 5433 -d opencurelabs -f db/schema.sql
```

### 5. Coordinator LLM

The coordinator uses Gemini 2.0 Flash Lite via the Gemini API for task routing
and agent reasoning. Set your `GENAI_API_KEY` in `.env`.

### 6. Environment Variables

```bash
# Create .env from template
cp .env.example .env
nano .env
```

**Required keys:**

| Key | Where to get it | Used by |
|---|---|---|
| `GENAI_API_KEY` | [aistudio.google.com](https://aistudio.google.com) | Gemini coordinator LLM |
| `ANTHROPIC_API_KEY` | [console.anthropic.com](https://console.anthropic.com) | Claude Opus 4.6 reviewer |
| `XAI_API_KEY` | [console.x.ai](https://console.x.ai) | Grok researcher agent |

**Optional keys:**

| Key | Where to get it | Used by |
|---|---|---|
| `DISCORD_WEBHOOK_URL_AGENT_LOGS` | Discord → Integrations → Webhooks | Agent trace logging (#agent-logs) |
| `DISCORD_WEBHOOK_URL_RESULTS` | Discord → Integrations → Webhooks | Findings & results (#results) |
| `NVIDIA_API_KEY` | [build.nvidia.com](https://build.nvidia.com) | NIM endpoints (optional) |
| `VAST_AI_KEY` | [vast.ai](https://vast.ai) | Burst GPU compute |

### 7. Verify Installation

```bash
source .venv/bin/activate

# Run the neoantigen pipeline on synthetic data
python tests/test_neoantigen.py
```

**Expected output:** 6 strong binders from KRAS G12V, 2 weak binders from TP53
R175H, all tests pass.

### 8. Launch

```bash
bash dashboard/lab.sh
```

This opens a 6-pane Zellij session:

```
┌──────────────┬──────────────┐
│ COORDINATOR  │    GROK      │
├──────────────┼──────────────┤
│    LOGS      │  POSTGRES    │
├──────────────┼──────────────┤
│  DASHBOARD   │   SHELL      │
└──────────────┴──────────────┘
```

| Pane | Purpose |
|---|---|
| **COORDINATOR** | Run `nat run` commands here |
| **GROK** | Grok researcher workspace (runs from `/workspace`) |
| **LOGS** | Live tail of agent activity log |
| **POSTGRES** | Auto-refreshing view of recent agent runs |
| **DASHBOARD** | Live findings CLI (auto-refreshing) |
| **SHELL** | General purpose terminal with venv activated |

**Keyboard shortcuts:**
- `Ctrl+p` then arrow keys — switch between panes
- `Ctrl+q` then `d` — detach (session keeps running)
- `bash dashboard/lab.sh` — reattach to existing session

---

## Running Your First Pipeline

In the **COORDINATOR** pane:

```bash
nat run --config_file coordinator/labclaw_workflow.yaml \
  --input "predict neoantigens for KRAS G12V in HLA-A*02:01"
```

The coordinator will:
1. Route the task to the neoantigen prediction skill
2. Run the VCF → pyensembl → MHCflurry pipeline
3. Validate output through guardrails
4. Send novel results to Claude Opus for scientific critique
5. Log everything to PostgreSQL and Discord

---

## Manual Pipeline Mode

If you want to run pipelines **without the LLM coordinator** (no Gemini API
needed), use the CLI scripts in `pipelines/` directly:

```bash
source .venv/bin/activate

# Neoantigen prediction
python pipelines/run_pipeline.py neoantigen \
  --vcf data/sample.vcf \
  --hla "HLA-A*02:01,HLA-B*07:02"

# Variant discovery
python pipelines/run_pipeline.py variant_discovery \
  --variant "chr17:7674220:C>T" --gene TP53

# Drug screening
python pipelines/run_pipeline.py drug_screen \
  --smiles "CC(=O)Oc1ccccc1C(O)=O" --receptor data/target.pdb
```

These scripts call the same LabClaw skills as the coordinator but skip the LLM
routing step. Results are still logged to PostgreSQL and go through the
post-execution orchestrator (guardrails, critique, publishing).

**When to use manual mode:**
- Debugging a specific skill without LLM overhead
- Running batch jobs where the task is already known
- Environments where the Gemini API is unavailable

**Eval mode** runs predefined benchmark cases with known expected outcomes:

```bash
python pipelines/eval_mode.py                     # Run all benchmarks
python pipelines/eval_mode.py --suite neoantigen   # Run specific suite
python pipelines/eval_mode.py --verbose            # Detailed output
```

---

## Optional: Grok Researcher Agent

Grok requires [Bun](https://bun.sh) and grok-cli:

```bash
# Install Bun
curl -fsSL https://bun.sh/install | bash
source ~/.bashrc

# Install grok-cli
bun add -g @vibe-kit/grok-cli

# Set API key (should already be in .env)
export XAI_API_KEY="your_key_here"

# Run from the workspace directory (required)
cd workspace/
grok --max-tool-rounds 200 --prompt "search bioRxiv for new neoantigen datasets this week"
```

---

## Optional: NVIDIA GPU Setup

For local GPU compute (structure prediction, molecular docking, QSAR):

1. Install NVIDIA drivers for your GPU
2. Install CUDA Toolkit 12.x from [developer.nvidia.com/cuda-downloads](https://developer.nvidia.com/cuda-downloads)
3. Verify: `nvidia-smi` should show your GPU

The RTX 5070 or equivalent is recommended. GPU is used by scientific skills, not
by the coordinator (which uses the Gemini API).

---

## What the Setup Script Does

`scripts/setup.sh` automates the manual steps above:

| Step | What it does |
|---|---|
| 1 | Installs system packages via apt |
| 2 | Creates Python 3.11+ venv |
| 3 | Installs requirements.txt + agentiq_labclaw |
| 4 | Downloads pyensembl and MHCflurry models |
| 5 | Starts PostgreSQL, creates database, applies schema |
| 6 | Creates .env from template (if missing) |
| 7 | Installs pre-commit security hook |
| 8 | Creates required directories |
| 9 | Runs verification checks |

The script is idempotent — running it again skips steps that are already complete.

---

## Stopping

```bash
bash dashboard/stop.sh
```

This auto-commits any uncommitted changes, pushes to GitHub, and kills the Zellij
session.

---

## Troubleshooting

| Problem | Solution |
|---|---|
| `nat: command not found` | `source .venv/bin/activate && pip install nvidia-nat` |
| PostgreSQL won't start | Check port: `sudo -u postgres psql -c "SHOW port;"` |
| `psql: could not connect` | `sudo service postgresql start` |
| pyensembl errors | `pyensembl install --release 110 --species human` |
| MHCflurry import error | `mhcflurry-downloads fetch models_class1 models_class1_pan models_class1_presentation` |
| `.env not found` | `cp .env.example .env && nano .env` |
| Pre-commit hook blocks commit | Fix findings, or bypass with `git commit --no-verify` |
| Zellij session exists | `bash dashboard/lab.sh` will reattach automatically |

---

## File Reference

| File | Purpose |
|---|---|
| `scripts/setup.sh` | Automated full setup |
| `dashboard/lab.sh` | Launch Zellij control panel |
| `dashboard/stop.sh` | Shutdown and auto-commit |
| `.env.example` | Template for API keys |
| `requirements.txt` | Python dependencies |
| `db/schema.sql` | PostgreSQL schema |
| `CONTRIBUTING.md` | Guide for contributors |
| `LABCLAW.md` | Architecture specification |
