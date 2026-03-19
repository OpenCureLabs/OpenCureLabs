#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
#  OpenCure Labs — Zellij Control Panel
#  Launches the full OpenCure Labs environment in a 6-pane Zellij session.
#
#  Usage:  ./dashboard/lab.sh          (from anywhere)
#          bash /root/opencurelabs/dashboard/lab.sh
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail

PROJECT="/root/opencurelabs"
SESSION="opencurelabs"
LOGFILE="$PROJECT/logs/agent.log"
ZELLIJ_CFG="$PROJECT/dashboard/zellij"
PG_PORT=5433

# ── Dependency check ─────────────────────────────────────────────────────────
if ! command -v zellij &>/dev/null; then
    echo "[OpenCure Labs] Zellij not found — installing..."
    ZELLIJ_VERSION="v0.41.2"
    ARCH="$(uname -m)"
    case "$ARCH" in
        x86_64)  TARGET="x86_64-unknown-linux-musl" ;;
        aarch64) TARGET="aarch64-unknown-linux-musl" ;;
        *)       echo "[OpenCure Labs] Unsupported architecture: $ARCH"; exit 1 ;;
    esac
    curl -fsSL "https://github.com/zellij-org/zellij/releases/download/${ZELLIJ_VERSION}/zellij-${TARGET}.tar.gz" \
        -o /tmp/zellij.tar.gz
    tar -xzf /tmp/zellij.tar.gz -C /usr/local/bin
    chmod +x /usr/local/bin/zellij
    rm /tmp/zellij.tar.gz
    echo "[OpenCure Labs] Zellij $(zellij --version) installed."
fi

# ── Preflight checks ────────────────────────────────────────────────────────
WARNINGS=0

if [[ ! -d "$PROJECT/.venv" ]]; then
    echo "[OpenCure Labs] ⚠️  No Python venv found at $PROJECT/.venv"
    echo "               Run: bash scripts/setup.sh"
    WARNINGS=$((WARNINGS + 1))
fi

if [[ ! -f "$PROJECT/.env" ]]; then
    echo "[OpenCure Labs] ⚠️  No .env file found — API keys not configured"
    echo "               Run: cp .env.example .env && nano .env"
    WARNINGS=$((WARNINGS + 1))
fi

if ! command -v nat &>/dev/null && [[ -d "$PROJECT/.venv" ]]; then
    # shellcheck source=/dev/null
    source "$PROJECT/.venv/bin/activate" 2>/dev/null
    if ! command -v nat &>/dev/null; then
        echo "[OpenCure Labs] ⚠️  NeMo Agent Toolkit (nat) not installed"
        echo "               Run: pip install nvidia-nat"
        WARNINGS=$((WARNINGS + 1))
    fi
fi

if [[ $WARNINGS -gt 0 ]]; then
    echo ""
    echo "[OpenCure Labs] $WARNINGS warning(s) — some panes may not work correctly."
    echo "               Run 'bash scripts/setup.sh' for full setup."
    echo ""
    sleep 2
fi

# ── Ensure log file exists ───────────────────────────────────────────────────
mkdir -p "$PROJECT/logs"
touch "$LOGFILE"

# ── Ensure PostgreSQL is running ─────────────────────────────────────────────
if ! pg_isready -p "$PG_PORT" -q 2>/dev/null; then
    echo "[OpenCure Labs] Starting PostgreSQL on port $PG_PORT..."
    service postgresql start 2>/dev/null || true
    sleep 1
fi

# ── Reattach if session already exists ───────────────────────────────────────
if zellij list-sessions -s 2>&1 | grep -q "^${SESSION}$"; then
    echo "[OpenCure Labs] Session '$SESSION' already running — reattaching."
    exec zellij attach "$SESSION"
fi

# ── Start web dashboard server (background) ──────────────────────────────────
if ! curl -s http://127.0.0.1:8787 &>/dev/null; then
    echo "[OpenCure Labs] Starting web dashboard → http://localhost:8787"
    # shellcheck source=/dev/null
    (cd "$PROJECT" && source "$PROJECT/.venv/bin/activate" && python dashboard/dashboard.py >>"$PROJECT/logs/dashboard.log" 2>&1 &)
    sleep 1
else
    echo "[OpenCure Labs] Web dashboard already running on :8787"
fi

# ── Launch Zellij ────────────────────────────────────────────────────────────
echo "[OpenCure Labs] Launching Zellij session '$SESSION'..."
exec env ZELLIJ_CONFIG_DIR="$ZELLIJ_CFG" zellij -s "$SESSION"
