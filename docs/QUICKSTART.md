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

## Optional: Vast.ai GPU Burst Compute

If you don't have a local GPU, or need to scale to many parallel jobs (batch
mode), OpenCure Labs can provision GPU instances on [Vast.ai](https://vast.ai)
automatically.

### 1. Create a Vast.ai Account

Sign up at [cloud.vast.ai](https://cloud.vast.ai) and add credit ($5–$25
is enough for testing). Instances cost $0.06–$0.50/hr depending on the GPU.

### 2. Get Your API Key

Go to **Account → API Keys** on the Vast.ai dashboard and copy your key.
Add it to your `.env` file:

```bash
VAST_AI_KEY=your_key_here
```

### 3. Generate an SSH Key

OpenCure Labs uses SSH to connect to Vast.ai instances. Generate a dedicated
key pair:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/xpclabs -N "" -C "opencurelabs-agent"
```

This creates `~/.ssh/xpclabs` (private) and `~/.ssh/xpclabs.pub` (public).

### 4. Register Your SSH Key with Vast.ai

This is a **required step** — without it, instances will provision but OpenCure
Labs won't be able to SSH in to verify setup or run jobs.

```bash
# Install the Vast.ai CLI (included in requirements.txt)
pip install vastai

# Set your API key for the CLI
vastai set api-key YOUR_KEY_HERE

# Register your SSH public key
vastai create ssh-key ~/.ssh/xpclabs.pub

# Verify it's registered
vastai show ssh-keys
```

You should see your key listed. The SSH key is attached automatically to every
new instance that OpenCure Labs provisions.

> **Important:** `vastai create ssh-key` registers the key on your *account*.
> OpenCure Labs also auto-attaches it to each new instance via the API. If you
> see SSH authentication failures, check that:
> - `~/.ssh/xpclabs` and `~/.ssh/xpclabs.pub` both exist
> - `vastai show ssh-keys` lists your key
> - The key was created *before* provisioning instances

### 5. Docker Image for Vast.ai Instances

Vast.ai instances use a custom Docker image with all bioinformatics tools
pre-installed (RDKit, gnina, MHCflurry, fastp, pyensembl data, etc.). This
eliminates multi-minute setup delays and dependency failures.

**Default image:**
`ghcr.io/opencurelabs/labclaw-gpu:latest`

The image is built automatically by CI when `docker/**` or
`packages/agentiq_labclaw/**` change on the `main` branch.

**To use a custom image** (e.g. from your fork):

```bash
# Build locally
cd docker/
bash build-push.sh

# Or just build without pushing
BUILD_ONLY=1 bash build-push.sh
```

Set the `LABCLAW_DOCKER_IMAGE` environment variable in `.env` to override:

```bash
LABCLAW_DOCKER_IMAGE=ghcr.io/yourorg/labclaw-gpu:latest
```

Or pass `--image` to the batch dispatcher:

```bash
python -m agentiq_labclaw.compute.batch_dispatcher \
  --count 20 --pool-size 4 \
  --image ghcr.io/yourorg/labclaw-gpu:latest
```

### 6. Create a GitHub Release with the Wheel (Fork-specific)

If you forked the repo, Vast.ai instances install the `agentiq_labclaw` package
from a pre-built wheel attached to your GitHub Releases — not by cloning the
entire repo (which is slow).

The CI workflow (`release.yml`) builds and attaches the wheel automatically on
every release. To bootstrap the first one manually:

```bash
pip install build
python -m build packages/agentiq_labclaw/ --outdir dist/

# Create a release on your fork (requires gh CLI)
gh release create v0.1.0 dist/*.whl --title "v0.1.0" --notes "Initial release"
```

Set the `GITHUB_REPOSITORY` environment variable if your fork has a different
name:

```bash
# In .env
GITHUB_REPOSITORY=YourOrg/YourFork
```

For **private forks**, also set `GITHUB_TOKEN` in `.env` so the Vast.ai instance
can download the wheel via the GitHub API.

### 6. Test It

```bash
source .venv/bin/activate
python3 -c "
from agentiq_labclaw.compute.pool_manager import PoolManager
pool = PoolManager(target_size=1, gpu_required=True, max_cost_hr=0.35)
pool.scale_up()
pool.wait_for_ready(min_ready=1, timeout=300)
print('Instance ready:', pool.get_ready_instances())
pool.teardown()
"
```

This provisions 1 cheap GPU instance, waits for it to be ready, and tears it
down. Total cost: a few cents.

### How It Works

1. **Resolve wheel** — Python queries `GET /repos/{owner}/{repo}/releases/latest`
   to find the `.whl` asset URL (resolved once, shared across all instances)
2. **Provision** — Creates instances via Vast.ai API with the custom Docker
   image (`labclaw-gpu`) and an `onstart` script
3. **Attach SSH key** — POSTs your public key to each new instance
4. **Onstart runs** — Downloads and installs the wheel (~seconds — all other
   deps are pre-installed in the Docker image)
5. **Ready marker** — `/tmp/labclaw_ready` is created when setup succeeds
6. **SSH check** — OpenCure Labs polls for the marker via SSH every 10s
7. **Job dispatch** — Once ready, skills are executed remotely over SSH

### Auto-Download Data

Skills automatically download missing input data from public APIs:

| Skill | Data Source | What it Downloads |
|---|---|---|
| **Molecular Docking** | RCSB PDB | Receptor PDB file by ID (e.g. `1M17.pdb`) |
| **QSAR** | ChEMBL REST API | Bioactivity CSV for a target (e.g. `CHEMBL203`) |
| **Neoantigen** | Bundled VCF | Falls back to synthetic VCF from the wheel |
| **Sequencing QC** | Generated | Creates synthetic FASTQ pairs on-the-fly |
| **Structure** | UniProt | Resolves protein sequences by gene name |

Downloaded data is cached in `/tmp/labclaw_data/` and reused across runs.
No manual data preparation is needed to run Genesis Mode or batch dispatch.

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
| Vast.ai instances timeout (0 ready) | Run `vastai show ssh-keys` — if empty, run `vastai create ssh-key ~/.ssh/xpclabs.pub` |
| Vast.ai SSH asks for password | Key not attached. Check `~/.ssh/xpclabs.pub` exists and was registered before provisioning |
| Vast.ai pip install fails | Check `/tmp/labclaw_setup.log` on the instance. Ensure GitHub Release has a `.whl` attached |
| Vast.ai wheel filename error | Ensure the wheel was built with `python -m build` (produces a valid `name-version-py3-none-any.whl`) |

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
