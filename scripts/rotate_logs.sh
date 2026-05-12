#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
#  OpenCure Labs — Log Rotation
#  Compresses and prunes per-run genesis logs to keep logs/ from growing
#  unbounded. Safe to run from cron (idempotent, locks itself).
#
#  Default policy:
#    - Genesis run dirs older than 14 days  → tar.gz into logs/archive/
#    - Archives older than 90 days          → deleted
#    - The flat agent.log                   → rotated when > 50 MB (keep 5)
#
#  Override via env vars:
#    GENESIS_AGE_DAYS=14
#    ARCHIVE_AGE_DAYS=90
#    AGENT_LOG_MAX_BYTES=$((50 * 1024 * 1024))
#    AGENT_LOG_KEEP=5
#
#  Usage:  bash scripts/rotate_logs.sh [--dry-run]
#
#  Cron example (daily at 03:30):
#    30 3 * * *  cd /root/opencurelabs && bash scripts/rotate_logs.sh >> logs/rotate.log 2>&1
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail

PROJECT="$(cd "$(dirname "$0")/.." && pwd)"
LOGS_DIR="$PROJECT/logs"
ARCHIVE_DIR="$LOGS_DIR/archive"
LOCK_FILE="$LOGS_DIR/.rotate.lock"

GENESIS_AGE_DAYS="${GENESIS_AGE_DAYS:-14}"
ARCHIVE_AGE_DAYS="${ARCHIVE_AGE_DAYS:-90}"
AGENT_LOG_MAX_BYTES="${AGENT_LOG_MAX_BYTES:-$((50 * 1024 * 1024))}"
AGENT_LOG_KEEP="${AGENT_LOG_KEEP:-5}"

DRY_RUN=0
if [[ "${1:-}" == "--dry-run" ]]; then
    DRY_RUN=1
fi

log() { echo "[$(date -u +%FT%TZ)] $*"; }

run() {
    if [[ "$DRY_RUN" -eq 1 ]]; then
        log "DRY-RUN: $*"
    else
        eval "$@"
    fi
}

if [[ ! -d "$LOGS_DIR" ]]; then
    log "logs/ directory not found at $LOGS_DIR — nothing to do."
    exit 0
fi

# Single-instance lock
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    log "Another rotation is already running — exiting."
    exit 0
fi

mkdir -p "$ARCHIVE_DIR"

# ── 1. Archive aged genesis-* directories ────────────────────────────────────
log "Scanning for genesis-* dirs older than ${GENESIS_AGE_DAYS}d..."
archived=0
while IFS= read -r -d '' dir; do
    base="$(basename "$dir")"
    target="$ARCHIVE_DIR/${base}.tar.gz"
    if [[ -e "$target" ]]; then
        # Already archived (shouldn't happen, but be safe) — just remove the dir
        run "rm -rf -- '$dir'"
        continue
    fi
    log "  archiving $base"
    run "tar -czf '$target' -C '$LOGS_DIR' '$base' && rm -rf -- '$dir'"
    archived=$((archived + 1))
done < <(find "$LOGS_DIR" -maxdepth 1 -mindepth 1 -type d -name 'genesis-*' \
            -mtime "+${GENESIS_AGE_DAYS}" -print0 2>/dev/null)
log "  archived $archived genesis run(s)"

# ── 2. Prune very old archives ───────────────────────────────────────────────
log "Pruning archives older than ${ARCHIVE_AGE_DAYS}d..."
pruned=$(find "$ARCHIVE_DIR" -maxdepth 1 -type f -name 'genesis-*.tar.gz' \
            -mtime "+${ARCHIVE_AGE_DAYS}" -print 2>/dev/null | wc -l)
if [[ "$pruned" -gt 0 ]]; then
    run "find '$ARCHIVE_DIR' -maxdepth 1 -type f -name 'genesis-*.tar.gz' -mtime '+${ARCHIVE_AGE_DAYS}' -delete"
fi
log "  pruned $pruned archive(s)"

# ── 3. Rotate the flat agent.log if it has grown too large ───────────────────
AGENT_LOG="$LOGS_DIR/agent.log"
if [[ -f "$AGENT_LOG" ]]; then
    size=$(stat -c%s "$AGENT_LOG" 2>/dev/null || echo 0)
    if (( size > AGENT_LOG_MAX_BYTES )); then
        ts="$(date -u +%Y%m%d-%H%M%S)"
        log "Rotating agent.log (size ${size}B > ${AGENT_LOG_MAX_BYTES}B)"
        run "mv '$AGENT_LOG' '${AGENT_LOG}.${ts}' && gzip -9 '${AGENT_LOG}.${ts}' && : > '$AGENT_LOG'"
        # Keep only the N most recent rotated copies
        mapfile -t old < <(ls -1t "${AGENT_LOG}".*.gz 2>/dev/null | tail -n +$((AGENT_LOG_KEEP + 1)) || true)
        for f in "${old[@]:-}"; do
            [[ -n "$f" ]] && run "rm -f -- '$f'"
        done
    fi
fi

log "Rotation complete."
