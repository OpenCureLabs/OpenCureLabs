#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# OpenCure Labs — Stop running agents without quitting the dashboard
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

echo -e '\033[1;93m⏹  Stopping agents...\033[0m'

killed=0

# Kill nat run processes (the agent coordinator)
if pkill -f "nat run" 2>/dev/null; then
    echo "  ✓ Stopped nat run"
    ((killed++)) || true
fi

# Kill run_research.sh (the launcher script / continuous loop)
if pkill -f "run_research.sh" 2>/dev/null; then
    echo "  ✓ Stopped run_research.sh"
    ((killed++)) || true
fi

if [ "$killed" -eq 0 ]; then
    echo -e '\033[2m  No agents were running.\033[0m'
else
    echo -e '\033[1;92m  ✓ Agents stopped. Dashboard still running.\033[0m'
fi

echo
echo -e '\033[2mPress Enter to close\033[0m'
read -r
