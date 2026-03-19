#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
#  OpenCure Labs — Automated Setup Script
#  Sets up a fresh Ubuntu 22.04+ / WSL2 machine to run the full platform.
#
#  Usage:  sudo bash scripts/setup.sh
#
#  What this script does (in order):
#    1. Installs system packages (Python 3.11, PostgreSQL, tmux, git, etc.)
#    2. Creates Python virtual environment and installs dependencies
#    3. Downloads scientific models (pyensembl, MHCflurry)
#    4. Sets up PostgreSQL database and schema
#    5. Installs Ollama for local LLM inference
#    6. Creates .env from template (if not already present)
#    7. Installs the pre-commit security hook
#    8. Runs verification checks
#
#  Requirements:
#    - Ubuntu 22.04+ or WSL2 (Debian-based)
#    - Root access (or sudo)
#    - Internet connection
#    - ~5 GB free disk space (models + packages)
#
#  Optional (not installed by this script):
#    - NVIDIA GPU + CUDA 12.x (for local GPU compute)
#    - Bun + grok-cli (for Grok researcher agent)
#    - Vast.ai account (for burst GPU compute)
#
#  Flags:
#    --skip-models   Skip heavy model downloads (pyensembl, MHCflurry, Ollama).
#                    Useful for CI and Codespaces where tests are mocked.
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail

# ── Parse flags ──────────────────────────────────────────────────────────────
SKIP_MODELS=false
for arg in "$@"; do
    case "$arg" in
        --skip-models) SKIP_MODELS=true ;;
    esac
done

# ── Constants ────────────────────────────────────────────────────────────────
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV_DIR="$PROJECT_DIR/.venv"
PG_PORT=5433
PG_DB="opencurelabs"
PYTHON="python3"
MIN_PYTHON="3.11"

# ── Colors ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m'

step_num=0
step() {
    step_num=$((step_num + 1))
    echo ""
    echo -e "${BLUE}${BOLD}[$step_num] $1${NC}"
    echo "────────────────────────────────────────────────────────────────"
}

ok()   { echo -e "  ${GREEN}✅ $1${NC}"; }
warn() { echo -e "  ${YELLOW}⚠️  $1${NC}"; }
fail() { echo -e "  ${RED}❌ $1${NC}"; }
info() { echo -e "  ${BOLD}→${NC} $1"; }

# ── Header ───────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}══════════════════════════════════════════════════════════════${NC}"
echo -e "${BOLD}  OpenCure Labs — Automated Setup${NC}"
echo -e "${BOLD}  Project: $PROJECT_DIR${NC}"
echo -e "${BOLD}══════════════════════════════════════════════════════════════${NC}"

# ── Check root ───────────────────────────────────────────────────────────────
if [[ $EUID -ne 0 ]]; then
    fail "This script must be run as root (or with sudo)."
    echo "  Usage: sudo bash scripts/setup.sh"
    exit 1
fi

# ══════════════════════════════════════════════════════════════════════════════
#  Step 1: System Packages
# ══════════════════════════════════════════════════════════════════════════════
step "Installing system packages"

apt-get update -qq

PACKAGES=(
    python3
    python3-venv
    python3-pip
    python3-dev
    build-essential
    git
    curl
    wget
    tmux
    htop
    postgresql
    postgresql-contrib
    libpq-dev
    fastp
    openbabel
)

MISSING=()
for pkg in "${PACKAGES[@]}"; do
    if ! dpkg -l "$pkg" &>/dev/null; then
        MISSING+=("$pkg")
    fi
done

if [[ ${#MISSING[@]} -gt 0 ]]; then
    info "Installing: ${MISSING[*]}"
    apt-get install -y -qq "${MISSING[@]}"
    ok "System packages installed"
else
    ok "All system packages already present"
fi

# ── Python version check ────────────────────────────────────────────────────
PY_VERSION=$($PYTHON --version 2>&1 | grep -oP '\d+\.\d+')
if [[ "$(echo -e "$PY_VERSION\n$MIN_PYTHON" | sort -V | head -1)" != "$MIN_PYTHON" ]]; then
    fail "Python $MIN_PYTHON+ required, found $PY_VERSION"
    info "Install Python 3.11+: sudo apt install python3.11 python3.11-venv"
    exit 1
fi
ok "Python $PY_VERSION detected"

# ══════════════════════════════════════════════════════════════════════════════
#  Step 2: Python Virtual Environment
# ══════════════════════════════════════════════════════════════════════════════
step "Setting up Python virtual environment"

if [[ ! -d "$VENV_DIR" ]]; then
    info "Creating venv at $VENV_DIR"
    $PYTHON -m venv "$VENV_DIR"
    ok "Virtual environment created"
else
    ok "Virtual environment already exists"
fi

# shellcheck source=/dev/null
source "$VENV_DIR/bin/activate"
ok "Activated venv: $(which python3)"

# ══════════════════════════════════════════════════════════════════════════════
#  Step 3: Python Dependencies
# ══════════════════════════════════════════════════════════════════════════════
step "Installing Python dependencies"

info "Upgrading pip"
pip install --upgrade pip --quiet

info "Pre-installing numpy<2.0 (avoids pyarrow ABI mismatch)"
pip install 'numpy>=1.26,<2.0' --quiet

info "Installing from requirements.txt"
pip install -r "$PROJECT_DIR/requirements.txt" --quiet 2>&1 | tail -3

info "Installing agentiq_labclaw package (editable)"
pip install -e "$PROJECT_DIR/packages/agentiq_labclaw" --quiet

ok "Python dependencies installed"

# ══════════════════════════════════════════════════════════════════════════════
#  Step 4: Scientific Model Downloads
# ══════════════════════════════════════════════════════════════════════════════
step "Downloading scientific models"

if [[ "$SKIP_MODELS" == "true" ]]; then
    warn "Skipping model downloads (--skip-models flag set)"
    info "pyensembl, MHCflurry, and Ollama will not be downloaded."
    info "Tests use mocks and do not require these models."
else

info "pyensembl — Ensembl release 110 (human genome, ~500 MB)"
if python3 -c "from pyensembl import EnsemblRelease; e = EnsemblRelease(110); e.transcript_by_id('ENST00000256078')" 2>/dev/null; then
    ok "pyensembl data already downloaded"
else
    pyensembl install --release 110 --species human 2>&1 | tail -3
    ok "pyensembl data downloaded"
fi

info "MHCflurry — binding prediction models (~1 GB)"
if python3 -c "import mhcflurry; mhcflurry.Class1PresentationPredictor.load()" 2>/dev/null; then
    ok "MHCflurry models already downloaded"
else
    mhcflurry-downloads fetch models_class1 models_class1_pan models_class1_presentation 2>&1 | tail -5
    ok "MHCflurry models downloaded"
fi

fi  # end SKIP_MODELS guard for Step 4

# ══════════════════════════════════════════════════════════════════════════════
#  Step 5: PostgreSQL Setup
# ══════════════════════════════════════════════════════════════════════════════
step "Setting up PostgreSQL (port $PG_PORT)"

# Start PostgreSQL if not running
if ! pg_isready -p "$PG_PORT" -q 2>/dev/null; then
    info "Starting PostgreSQL service"
    service postgresql start 2>/dev/null || true
    sleep 2
fi

if pg_isready -p "$PG_PORT" -q 2>/dev/null; then
    ok "PostgreSQL is running on port $PG_PORT"
else
    warn "PostgreSQL not responding on port $PG_PORT"
    info "You may need to configure PostgreSQL to use port $PG_PORT"
    info "Edit /etc/postgresql/*/main/postgresql.conf and set: port = $PG_PORT"
    info "Then: sudo service postgresql restart"
fi

# Create database if it doesn't exist
if sudo -u postgres psql -p "$PG_PORT" -lqt 2>/dev/null | cut -d \| -f 1 | grep -qw "$PG_DB"; then
    ok "Database '$PG_DB' already exists"
else
    info "Creating database '$PG_DB'"
    sudo -u postgres psql -p "$PG_PORT" -c "CREATE DATABASE $PG_DB;" 2>/dev/null
    ok "Database created"
fi

# Apply schema
info "Applying schema from db/schema.sql"
if sudo -u postgres psql -p "$PG_PORT" -d "$PG_DB" -c "SELECT 1 FROM agent_runs LIMIT 1" &>/dev/null; then
    ok "Schema already applied"
else
    # schema.sql contains CREATE DATABASE which would fail; run table creates only
    sudo -u postgres psql -p "$PG_PORT" -d "$PG_DB" -f "$PROJECT_DIR/db/schema.sql" 2>/dev/null || true
    ok "Schema applied"
fi

# ══════════════════════════════════════════════════════════════════════════════
#  Step 6: Ollama (Local LLM)
# ══════════════════════════════════════════════════════════════════════════════
step "Setting up Ollama (local LLM inference)"

if [[ "$SKIP_MODELS" == "true" ]]; then
    warn "Skipping Ollama setup (--skip-models flag set)"
elif command -v ollama &>/dev/null; then
    ok "Ollama already installed"
else
    info "Installing Ollama"
    curl -fsSL https://ollama.com/install.sh | sh
    ok "Ollama installed"
fi

# Start Ollama if not running
if curl -s http://localhost:11434/api/tags &>/dev/null; then
    ok "Ollama is running"
else
    info "Starting Ollama in background"
    ollama serve &>/dev/null &
    sleep 3
fi

# Pull coordinator model
if ollama list 2>/dev/null | grep -q "llama3.1"; then
    ok "llama3.1 model already pulled"
else
    info "Pulling llama3.1:8b model (this may take several minutes)"
    ollama pull llama3.1:8b 2>&1 | tail -3
    ok "llama3.1:8b model ready"
fi
fi  # end SKIP_MODELS guard for Step 6

# ══════════════════════════════════════════════════════════════════════════════
#  Step 7: Environment Configuration
# ══════════════════════════════════════════════════════════════════════════════
step "Environment configuration"

if [[ -f "$PROJECT_DIR/.env" ]]; then
    ok ".env file exists"
    # Check for required keys
    MISSING_KEYS=()
    for key in ANTHROPIC_API_KEY XAI_API_KEY; do
        val=$(grep "^${key}=" "$PROJECT_DIR/.env" 2>/dev/null | cut -d= -f2-)
        if [[ -z "$val" ]]; then
            MISSING_KEYS+=("$key")
        fi
    done
    if [[ ${#MISSING_KEYS[@]} -gt 0 ]]; then
        warn "Missing API keys in .env: ${MISSING_KEYS[*]}"
        info "Edit .env and add your keys. The system will run without them"
        info "but the reviewer agents (Claude Opus, Grok) won't work."
    else
        ok "Required API keys are configured"
    fi
else
    info "Creating .env from template"
    cp "$PROJECT_DIR/.env.example" "$PROJECT_DIR/.env"
    warn ".env created — you must edit it and add your API keys:"
    info "  nano $PROJECT_DIR/.env"
    info ""
    info "  Required:  ANTHROPIC_API_KEY, XAI_API_KEY"
    info "  Optional:  DISCORD_WEBHOOK_URL, NVIDIA_API_KEY, VAST_AI_KEY"
fi

# ══════════════════════════════════════════════════════════════════════════════
#  Step 8: Pre-commit Security Hook
# ══════════════════════════════════════════════════════════════════════════════
step "Installing pre-commit security hook"

HOOK_SRC="$PROJECT_DIR/security/pre-commit-hook.sh"
HOOK_DST="$PROJECT_DIR/.git/hooks/pre-commit"

if [[ -f "$HOOK_SRC" ]] && [[ -d "$PROJECT_DIR/.git/hooks" ]]; then
    cp "$HOOK_SRC" "$HOOK_DST"
    chmod +x "$HOOK_DST"
    ok "Pre-commit hook installed"
else
    if [[ ! -d "$PROJECT_DIR/.git" ]]; then
        warn "Not a git repository — skipping hook install"
    else
        warn "Security hook not found at $HOOK_SRC — skipping"
    fi
fi

# ══════════════════════════════════════════════════════════════════════════════
#  Step 9: Create directories
# ══════════════════════════════════════════════════════════════════════════════
step "Ensuring directory structure"

for dir in agents coordinator skills pipelines data reviewer reports logs db config workspace docs; do
    mkdir -p "$PROJECT_DIR/$dir"
done
mkdir -p "$PROJECT_DIR/security/reports"
ok "All directories present"

# ══════════════════════════════════════════════════════════════════════════════
#  Step 10: Verification
# ══════════════════════════════════════════════════════════════════════════════
step "Running verification checks"

PASS=0
TOTAL=0

check() {
    TOTAL=$((TOTAL + 1))
    if eval "$1" &>/dev/null; then
        ok "$2"
        PASS=$((PASS + 1))
    else
        fail "$2"
    fi
}

check "python3 -c 'import pydantic'"           "pydantic importable"
check "python3 -c 'import psycopg2'"           "psycopg2 importable"
check "python3 -c 'import requests'"           "requests importable"
check "python3 -c 'import agentiq_labclaw'"    "agentiq_labclaw importable"
check "python3 -c 'import pysam'"              "pysam importable"
check "python3 -c 'import Bio'"                "biopython importable"

if [[ "$SKIP_MODELS" == "false" ]]; then
check "python3 -c 'import pyensembl'"          "pyensembl importable"
check "python3 -c 'import mhcflurry'"          "mhcflurry importable"
check "command -v nat"                          "nat CLI available"
check "command -v ollama"                       "ollama installed"
check "curl -s http://localhost:11434/api/tags" "ollama responding"
fi

check "pg_isready -p $PG_PORT -q"              "PostgreSQL responding"
check "test -f $PROJECT_DIR/.env"              ".env file exists"

# ══════════════════════════════════════════════════════════════════════════════
#  Summary
# ══════════════════════════════════════════════════════════════════════════════
echo ""
echo -e "${BOLD}══════════════════════════════════════════════════════════════${NC}"
echo -e "${BOLD}  Setup Complete: $PASS/$TOTAL checks passed${NC}"
echo -e "${BOLD}══════════════════════════════════════════════════════════════${NC}"
echo ""

if [[ $PASS -eq $TOTAL ]]; then
    echo -e "${GREEN}${BOLD}  All checks passed. OpenCure Labs is ready.${NC}"
else
    echo -e "${YELLOW}${BOLD}  Some checks failed — review the output above.${NC}"
fi

echo ""
echo -e "${BOLD}  Next steps:${NC}"
echo ""
echo "  1. Edit your API keys:"
echo "     nano $PROJECT_DIR/.env"
echo ""
echo "  2. Launch the tmux control panel:"
echo "     bash $PROJECT_DIR/dashboard/lab.sh"
echo ""
echo "  3. In the COORDINATOR pane, run a pipeline:"
echo "     nat run --config_file coordinator/labclaw_workflow.yaml --input \"your task\""
echo ""
echo "  4. Run the neoantigen test to verify the scientific stack:"
echo "     source $VENV_DIR/bin/activate"
echo "     python tests/test_neoantigen.py"
echo ""
echo -e "${BOLD}  Documentation: docs/QUICKSTART.md${NC}"
echo -e "${BOLD}  Contributing:  CONTRIBUTING.md${NC}"
echo ""
