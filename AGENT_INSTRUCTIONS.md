# OpenCure Labs — Agent Bootstrap Instructions

You have root access and full control of a private WSL2 VM running Ubuntu 24.04
on a dedicated NVMe (D:\WSL\OpenCure-Labs). The project is OpenCure Labs — an autonomous
AI-for-Science platform. Read /root/xpc-labs/README.md for full context before
doing anything.

---

## ⚠️ FIRST — Secure the .env file (do this before anything else)

A .env file with real API keys already exists on disk. Before any git operations:

```bash
cd /root/xpc-labs

# 1. Ensure .gitignore exists and .env is in it
grep -q "^\.env$" .gitignore || echo ".env" >> .gitignore

# 2. If git is already initialized, make sure .env is not tracked
git ls-files .env

# If the above returns ".env", remove it from git's index immediately:
git rm --cached .env

# 3. Verify .env does not appear in git status
git status
```

**Never commit .env under any circumstances. If keys are ever accidentally
committed, they must be considered compromised and rotated immediately.**

Also create .env.example with placeholder values (no real keys) for documentation:

```
NVIDIA_API_KEY=
XAI_API_KEY=
ANTHROPIC_API_KEY=
DISCORD_WEBHOOK_URL=
POSTGRES_URL=postgresql://localhost/opencurelabs
VAST_AI_KEY=
```

---

## Your tasks in order:

### 1. Bootstrap the VM

```bash
apt update && apt upgrade -y

apt install -y python3.11 python3.11-venv python3-pip git curl wget \
  build-essential unzip postgresql postgresql-contrib nodejs npm

# GitHub CLI
curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | \
  dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | \
  tee /etc/apt/sources.list.d/github-cli.list
apt update && apt install gh -y

# Bun (for grok-cli)
curl -fsSL https://bun.sh/install | bash
source ~/.bashrc

# NVIDIA NeMo Agent Toolkit
python3.11 -m venv /root/xpc-labs/.venv
source /root/xpc-labs/.venv/bin/activate
pip install aiq

# Grok CLI
bun add -g @vibe-kit/grok-cli
```

### 2. Set up the folder structure

Create the following under /root/xpc-labs:

```
agents/          # specialist agent configs (cancer, rare-disease, drug-response)
coordinator/     # NemoClaw/LabClaw YAML workflows (NeMo Agent Toolkit)
skills/          # LabClaw scientific skill modules
pipelines/       # genomics, docking, QSAR, structure prediction
data/            # ingestion connectors (TCGA, GEO, ClinVar, ChEMBL)
reviewer/        # Claude Opus + Grok reviewer agent configs
reports/         # generated PDF outputs
logs/            # agent run logs (also streamed to Discord)
db/              # PostgreSQL schemas and migrations
config/          # NeMo configs
workspace/       # Grok's designated working directory (sandboxed)
docs/            # wiki source files
```

```bash
mkdir -p /root/xpc-labs/{agents,coordinator,skills,pipelines,data,reviewer,reports,logs,db,config,workspace,docs}
```

### 3. CLAUDE.md

Create /root/xpc-labs/CLAUDE.md — this file is read automatically by Claude Code
agents at the start of every session. It should contain:

- Project overview (summarized from README.md)
- Folder structure map
- Key conventions:
  - Always activate venv: `source /root/xpc-labs/.venv/bin/activate`
  - Always work in /root/xpc-labs
  - Grok agent must always run from /root/xpc-labs/workspace/ only
  - Never commit .env — keys live on disk only, never in git
  - Never overwrite README.md — it is the source of truth
- Agent roles and responsibilities
- How to run the coordinator: `nat run --config_file coordinator/workflow.yaml`
- PostgreSQL connection: `postgresql://localhost/opencurelabs` (local, no auth in dev)
- Discord logging webhook: read from .env as DISCORD_WEBHOOK_URL
- GitHub repo: https://github.com/ShoneAnstey/OpenCureLabs

### 4. GitHub setup (no password commits)

```bash
# Generate SSH key (no passphrase)
ssh-keygen -t ed25519 -C "opencurelabs-agent" -f ~/.ssh/opencurelabs -N ""

# Display public key — add this to GitHub Settings → SSH Keys
cat ~/.ssh/opencurelabs.pub

# Configure SSH to use this key for GitHub
cat >> ~/.ssh/config << EOF
Host github.com
  HostName github.com
  User git
  IdentityFile ~/.ssh/opencurelabs
  IdentitiesOnly yes
EOF

chmod 600 ~/.ssh/config

# Git identity
git config --global user.email "agent@opencurelabs"
git config --global user.name "OpenCure Labs Agent"
```

After the public key has been added to GitHub, set the remote:

```bash
git remote set-url origin git@github.com:ShoneAnstey/OpenCureLabs.git

# Test connection
ssh -T git@github.com
```

### 5. Initialize and push the repo

```bash
cd /root/xpc-labs

git init

# Ensure .gitignore is comprehensive
cat > .gitignore << EOF
.env
.venv/
__pycache__/
*.pyc
*.pyo
*.egg-info/
data/raw/
logs/*.log
db/data/
.DS_Store
*.swp
EOF

# Verify .env is not staged
git status   # .env must NOT appear here

git add .
git commit -m "feat: initial OpenCure Labs bootstrap"
git branch -M main
git push -u origin main
```

### 6. GitHub Project + Wiki

Using the gh CLI (must be authenticated: `gh auth login`):

```bash
# Create Project board
gh project create --owner ShoneAnstey --title "OpenCure Labs" --format json

# Enable Wiki (via API)
gh api repos/ShoneAnstey/OpenCureLabs -X PATCH -f has_wiki=true
```

Create wiki pages for: Home, Architecture, Agents, Data Sources,
Compute Infrastructure, Roadmap — pulling content from README.md sections.

### 7. PostgreSQL setup

```bash
service postgresql start

sudo -u postgres psql << EOF
CREATE DATABASE opencurelabs;
\c opencurelabs

CREATE TABLE agent_runs (
  id SERIAL PRIMARY KEY,
  agent_name TEXT NOT NULL,
  started_at TIMESTAMP DEFAULT NOW(),
  completed_at TIMESTAMP,
  status TEXT,
  result_json JSONB
);

CREATE TABLE discovered_sources (
  id SERIAL PRIMARY KEY,
  url TEXT,
  domain TEXT,
  discovered_by TEXT,
  discovered_at TIMESTAMP DEFAULT NOW(),
  validated BOOLEAN DEFAULT FALSE,
  notes TEXT
);

CREATE TABLE pipeline_runs (
  id SERIAL PRIMARY KEY,
  pipeline_name TEXT NOT NULL,
  input_data JSONB,
  output_path TEXT,
  started_at TIMESTAMP DEFAULT NOW(),
  status TEXT
);

CREATE TABLE critique_log (
  id SERIAL PRIMARY KEY,
  run_id INTEGER REFERENCES pipeline_runs(id),
  reviewer TEXT,
  critique_json JSONB,
  timestamp TIMESTAMP DEFAULT NOW()
);

CREATE TABLE experiment_results (
  id SERIAL PRIMARY KEY,
  pipeline_run_id INTEGER REFERENCES pipeline_runs(id),
  result_type TEXT,
  result_data JSONB,
  novel BOOLEAN DEFAULT FALSE,
  timestamp TIMESTAMP DEFAULT NOW()
);
EOF
```

---

## Standing rules (always enforce)

- `.env` is never committed — keys live on disk only
- If `.env` is ever accidentally staged, run `git rm --cached .env` immediately and consider all keys in it compromised and rotate them
- Grok agent runs exclusively from `/root/xpc-labs/workspace/` — never from project root
- Always activate venv before running Python: `source /root/xpc-labs/.venv/bin/activate`
- All agent activity logs to `logs/` directory and Discord webhook
- README.md is the source of truth — never overwrite it
- GitHub repo: https://github.com/ShoneAnstey/OpenCureLabs
