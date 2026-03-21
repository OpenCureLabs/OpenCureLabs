#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
#  OpenCure Labs — Clean Shutdown
#  Stops the web dashboard, then tears down the Zellij session.
#  Research data persists in PostgreSQL. Code stays as-is until you commit.
#
#  Usage:  ./dashboard/stop.sh
# ──────────────────────────────────────────────────────────────────────────────
set -uo pipefail

PROJECT="/root/opencurelabs"
SESSION="opencurelabs"
PRE_QUIT=false

# --pre-quit flag: stop dashboard only, skip session kill (Zellij Quit handles that)
for arg in "$@"; do
    [[ "$arg" == "--pre-quit" ]] && PRE_QUIT=true
done

cd "$PROJECT"

echo "╔══════════════════════════════════════╗"
echo "║     OpenCure Labs — Shutting Down    ║"
echo "╚══════════════════════════════════════╝"

# ── 1. Kill web dashboard ────────────────────────────────────────────────────
echo "[1/2] Stopping web dashboard..."
if pkill -f "dashboard/dashboard.py" 2>/dev/null; then
    echo "       Dashboard stopped."
else
    echo "       No dashboard process found."
fi

# If --pre-quit, Zellij's Quit action will handle the session exit.
if $PRE_QUIT; then
    echo ""
    echo "Shutdown complete. Zellij will now exit."
    exit 0
fi

# ── 2. Kill Zellij session (manual invocation only) ──────────────────────────
echo "[2/2] Terminating Zellij session '$SESSION'..."
if zellij list-sessions 2>/dev/null | grep -q "^${SESSION}"; then
    zellij kill-session "$SESSION" 2>/dev/null
    echo "       Session killed."
else
    echo "       No active session found."
fi

echo ""
echo "Shutdown complete."
echo "Restart with: bash $PROJECT/dashboard/lab.sh"
echo ""
