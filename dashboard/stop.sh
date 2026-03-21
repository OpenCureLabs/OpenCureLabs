#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
#  OpenCure Labs — Clean Shutdown
#  Auto-saves uncommitted work, pushes to GitHub, then tears down the session.
#
#  Usage:  ./dashboard/stop.sh
# ──────────────────────────────────────────────────────────────────────────────
set -uo pipefail

PROJECT="/root/opencurelabs"
SESSION="opencurelabs"
PRE_QUIT=false

# --pre-quit flag: only auto-save/push, skip session kill (Zellij Quit handles that)
for arg in "$@"; do
    [[ "$arg" == "--pre-quit" ]] && PRE_QUIT=true
done

cd "$PROJECT"

echo "╔══════════════════════════════════════╗"
echo "║     OpenCure Labs — Shutting Down    ║"
echo "╚══════════════════════════════════════╝"

# ── 1. Auto-commit any uncommitted changes ───────────────────────────────────
echo "[1/3] Checking for uncommitted changes..."
source "$PROJECT/.venv/bin/activate" 2>/dev/null || true

if [[ -n "$(git -C "$PROJECT" status --porcelain 2>/dev/null)" ]]; then
    echo "       Staging and committing..."
    git -C "$PROJECT" add -A
    git -C "$PROJECT" commit -m "chore: auto-save on shutdown" 2>/dev/null || true
    echo "       Committed."
else
    echo "       Working tree clean — nothing to commit."
fi

# ── 2. Push to GitHub ────────────────────────────────────────────────────────
echo "[2/3] Pushing to GitHub..."
if git -C "$PROJECT" push origin main 2>/dev/null; then
    echo "       Pushed successfully."
else
    echo "       Push failed (offline or auth issue) — changes are committed locally."
fi

# ── 3. Kill web dashboard ────────────────────────────────────────────────────
echo "[3/3] Stopping web dashboard..."
if pkill -f "dashboard/dashboard.py" 2>/dev/null; then
    echo "       Dashboard stopped."
else
    echo "       No dashboard process found."
fi

# If --pre-quit, Zellij's Quit action will handle the session exit.
if $PRE_QUIT; then
    echo ""
    echo "Auto-save complete. Zellij will now exit."
    exit 0
fi

# ── 4. Kill Zellij session (manual invocation only) ──────────────────────────
echo "[4/4] Terminating Zellij session '$SESSION'..."
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
