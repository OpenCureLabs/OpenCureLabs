#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# OpenCure Labs — Stop running agents without quitting the dashboard
# ─────────────────────────────────────────────────────────────────────────────
set +e   # don't exit on pkill returning 1 (no processes found)

echo -e '\033[1;93m⏹  Stopping agents...\033[0m'

killed=0

# Kill all nat run processes first (children), then the launcher / loop.
# Order matters: kill children before parent so the parent's wait() doesn't
# see child exit codes and loop to the next Genesis round.
if pkill -TERM -f "nat run" 2>/dev/null; then
    echo "  ✓ Stopped nat run"
    ((killed++)) || true
fi

# Kill the entire run_research.sh process group so the `while true` outer
# loop and all of its children (parallel nat run subshells) die together.
# -KILL as a fallback after TERM in case the script has blocked signals.
if pkill -TERM -f "run_research.sh" 2>/dev/null; then
    echo "  ✓ Stopped run_research.sh"
    ((killed++)) || true
    sleep 1
    # Force-kill anything that survived SIGTERM
    pkill -KILL -f "run_research.sh" 2>/dev/null || true
    pkill -KILL -f "nat run" 2>/dev/null || true
fi

# Also kill any orphaned nat / agentiq processes left behind
pkill -TERM -f "agentiq_labclaw" 2>/dev/null || true
pkill -TERM -f "nemoagent\|nemo_agent\|nat run" 2>/dev/null || true

if [ "$killed" -eq 0 ]; then
    echo -e '\033[2m  No agents were running.\033[0m'
else
    echo -e '\033[1;92m  ✓ Agents stopped. Dashboard still running.\033[0m'
fi

# ── Destroy ALL Vast.ai instances (emergency cleanup) ────────────────────────
if command -v vastai > /dev/null 2>&1; then
    echo -e '\033[1;93m  Checking Vast.ai instances...\033[0m'
    INSTANCES=$(vastai show instances --raw 2>/dev/null || echo '[]')
    COUNT=$(echo "$INSTANCES" | python3 -c 'import json,sys; print(len(json.load(sys.stdin)))' 2>/dev/null || echo '0')
    if [ "$COUNT" -gt 0 ]; then
        echo -e "\033[1;91m  Found $COUNT Vast.ai instance(s) — destroying all...\033[0m"
        IDS=$(echo "$INSTANCES" | python3 -c '
import json, sys
for i in json.load(sys.stdin):
    print(i["id"])
' 2>/dev/null)
        for id in $IDS; do
            vastai destroy instance "$id" > /dev/null 2>&1 && echo "    ✓ Destroyed #$id" || echo "    ✗ Failed #$id"
        done
    else
        echo -e '\033[2m  No Vast.ai instances running.\033[0m'
    fi
fi

# ── Mark stale DB entries as failed ──────────────────────────────────────────
if command -v psql > /dev/null 2>&1; then
    psql -p 5433 -d opencurelabs -c \
        "UPDATE agent_runs SET status = 'failed', completed_at = NOW() WHERE status = 'running' AND started_at < NOW() - INTERVAL '5 minutes';" \
        > /dev/null 2>&1
fi

echo
echo -e '\033[2mPress Enter to close\033[0m'
read -r
