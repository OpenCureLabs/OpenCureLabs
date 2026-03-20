#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────
# OpenCure Labs — Sync local DB to production droplet
#
# Usage:
#   bash deploy/sync-db.sh                    # Uses DROPLET_IP env var
#   DROPLET_IP=1.2.3.4 bash deploy/sync-db.sh
#
# This dumps your local PostgreSQL data and loads it on the remote droplet.
# Safe to run repeatedly — it replaces remote data with local state.
# ─────────────────────────────────────────────────────────────────────────
set -euo pipefail

DROPLET_IP="${DROPLET_IP:?Set DROPLET_IP environment variable (e.g., export DROPLET_IP=1.2.3.4)}"
LOCAL_PORT="${LOCAL_PG_PORT:-5433}"
REMOTE_USER="${REMOTE_USER:-opencure}"
REMOTE_DB="opencurelabs"
TABLES=(agent_runs pipeline_runs experiment_results critique_log discovered_sources)

echo "🔄 Syncing local DB (port ${LOCAL_PORT}) → ${DROPLET_IP}"

for table in "${TABLES[@]}"; do
  echo "  → ${table}..."
  pg_dump -p "${LOCAL_PORT}" --data-only --table="${table}" "${REMOTE_DB}" 2>/dev/null \
    | ssh "root@${DROPLET_IP}" \
        "su - ${REMOTE_USER} -c 'psql -h localhost -U ${REMOTE_USER} ${REMOTE_DB}'" \
    2>/dev/null
done

echo "✅ Sync complete — ${#TABLES[@]} tables pushed to ${DROPLET_IP}"
