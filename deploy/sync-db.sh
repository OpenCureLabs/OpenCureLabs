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

DROPLET="${DROPLET_SSH:-opencure-do}"
LOCAL_PORT="${LOCAL_PG_PORT:-5433}"
REMOTE_USER="${REMOTE_USER:-opencure}"
REMOTE_DB="opencurelabs"
REMOTE_PW="${REMOTE_PG_PASSWORD:?Set REMOTE_PG_PASSWORD env var}"
TABLES=(agent_runs pipeline_runs experiment_results critique_log discovered_sources)

echo "🔄 Syncing local DB (port ${LOCAL_PORT}) → ${DROPLET}"

REMOTE_CMD="PGPASSWORD=${REMOTE_PW} psql -h 127.0.0.1 -U ${REMOTE_USER} ${REMOTE_DB}"

for table in "${TABLES[@]}"; do
  echo "  → ${table}..."
  # Truncate remote table first, then load local data
  {
    echo "TRUNCATE ${table} CASCADE;"
    pg_dump -p "${LOCAL_PORT}" --data-only --table="${table}" "${REMOTE_DB}" 2>/dev/null
  } | ssh "${DROPLET}" \
        "su - ${REMOTE_USER} -c '${REMOTE_CMD}'" \
    2>/dev/null
done

echo "✅ Sync complete — ${#TABLES[@]} tables pushed to ${DROPLET}"
