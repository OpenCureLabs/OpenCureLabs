#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# OpenCure Labs — Vast.ai Orphan Instance Watchdog
#
# Runs via cron every 3 minutes.  If no batch_dispatcher / nat run process is
# alive but Vast.ai instances still exist, destroys them all and logs the event.
#
# Install:  crontab -e  →  */3 * * * * /root/opencurelabs/scripts/vast_watchdog.sh
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

LOGFILE="/root/opencurelabs/logs/watchdog.log"
DB_PORT=5433
DB_NAME="opencurelabs"

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') [watchdog] $*" >> "$LOGFILE"
}

# ── 1. Check if a batch process is alive ─────────────────────────────────────
if pgrep -f "batch_dispatcher" > /dev/null 2>&1; then
    exit 0  # Process alive — nothing to do
fi
if pgrep -f "nat run" > /dev/null 2>&1; then
    exit 0  # Coordinator alive — nothing to do
fi
if pgrep -f "run_research.sh" > /dev/null 2>&1; then
    exit 0  # Launcher alive — nothing to do
fi

# ── 2. No process alive — check for orphaned instances ───────────────────────
# Vast.ai CLI must be available
if ! command -v vastai > /dev/null 2>&1; then
    log "ERROR: vastai CLI not found — cannot check for orphans"
    exit 1
fi

INSTANCES=$(vastai show instances --raw 2>/dev/null || echo "[]")
COUNT=$(echo "$INSTANCES" | python3 -c "import json,sys; print(len(json.load(sys.stdin)))" 2>/dev/null || echo "0")

if [ "$COUNT" -eq 0 ]; then
    exit 0  # No instances — all clear
fi

# ── 3. Orphans detected — destroy them ───────────────────────────────────────
log "ORPHAN ALERT: No batch process running but $COUNT Vast.ai instance(s) found — destroying all"

IDS=$(echo "$INSTANCES" | python3 -c "
import json, sys
instances = json.load(sys.stdin)
for i in instances:
    print(i['id'])
" 2>/dev/null)

destroyed=0
failed=0
for id in $IDS; do
    if vastai destroy instance "$id" > /dev/null 2>&1; then
        log "  Destroyed instance #$id"
        ((destroyed++)) || true
    else
        log "  FAILED to destroy instance #$id"
        ((failed++)) || true
    fi
done

log "Cleanup complete: $destroyed destroyed, $failed failed (of $COUNT total)"

# ── 4. Mark stale DB entries as failed ───────────────────────────────────────
if command -v psql > /dev/null 2>&1; then
    UPDATED=$(psql -p "$DB_PORT" -d "$DB_NAME" --no-align -t -c \
        "UPDATE agent_runs SET status = 'failed', completed_at = NOW() WHERE status = 'running' AND started_at < NOW() - INTERVAL '5 minutes' RETURNING id;" 2>/dev/null | wc -l)
    if [ "$UPDATED" -gt 0 ]; then
        log "  Marked $UPDATED stale agent_run(s) as failed"
    fi
fi
