#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
#  XPC Labs — Clean Shutdown
#  Auto-saves uncommitted work, pushes to GitHub, then tears down the session.
#
#  Usage:  ./scripts/stop.sh
# ──────────────────────────────────────────────────────────────────────────────
set -uo pipefail

PROJECT="/root/xpc-labs"
SESSION="xpclabs"

cd "$PROJECT"

echo "╔══════════════════════════════════════╗"
echo "║     XPC Labs — Shutting Down         ║"
echo "╚══════════════════════════════════════╝"

# ── 1. Auto-commit any uncommitted changes ───────────────────────────────────
echo "[1/4] Checking for uncommitted changes..."
source "$PROJECT/.venv/bin/activate" 2>/dev/null || true

if [[ -n "$(git -C "$PROJECT" status --porcelain 2>/dev/null)" ]]; then
    echo "       Staging and committing..."
    git -C "$PROJECT" add -A
    # Respect .gitignore — won't commit .env
    git -C "$PROJECT" commit -m "chore: auto-save on shutdown" --no-verify 2>/dev/null || true
    echo "       Committed."
else
    echo "       Working tree clean — nothing to commit."
fi

# ── 2. Push to GitHub ────────────────────────────────────────────────────────
echo "[2/4] Pushing to GitHub..."
if git -C "$PROJECT" push origin main 2>/dev/null; then
    echo "       Pushed successfully."
else
    echo "       Push failed (offline or auth issue) — changes are committed locally."
fi

# ── 3. Kill tmux session ────────────────────────────────────────────────────
echo "[3/4] Terminating tmux session '$SESSION'..."
if tmux has-session -t "$SESSION" 2>/dev/null; then
    tmux kill-session -t "$SESSION"
    echo "       Session killed."
else
    echo "       No active session found."
fi

# ── 4. Clean exit ────────────────────────────────────────────────────────────
echo "[4/4] Shutdown complete."
echo ""
echo "  To restart:  bash $PROJECT/scripts/lab.sh"
echo ""
