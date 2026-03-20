#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────
# OpenCure Labs — Update deployed dashboard
#
# Pulls latest code and restarts the dashboard service.
#
# Usage:
#   ssh root@$DROPLET_IP 'bash /opt/opencurelabs/deploy/update.sh'
# ─────────────────────────────────────────────────────────────────────────
set -euo pipefail

APP_DIR="/opt/opencurelabs"
APP_USER="opencure"

echo "📦 Pulling latest code..."
cd "${APP_DIR}"
su - "${APP_USER}" -c "cd ${APP_DIR} && git pull --ff-only"

echo "📦 Updating dependencies..."
su - "${APP_USER}" -c "cd ${APP_DIR} && source .venv/bin/activate && pip install -r requirements.txt -q"

echo "🔄 Restarting dashboard..."
systemctl restart opencurelabs-dashboard

echo "⏳ Waiting for health check..."
sleep 3
if curl -sf http://localhost:8787/health > /dev/null; then
  echo "✅ Dashboard healthy"
else
  echo "❌ Dashboard unhealthy — check: journalctl -u opencurelabs-dashboard -n 50"
  exit 1
fi
