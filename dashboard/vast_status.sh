#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# OpenCure Labs — Vast.ai Instance Status
# Shows active instances, GPU type, cost, and uptime.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

# Load API key from .env
VAST_KEY="${VAST_AI_KEY:-}"
if [[ -z "$VAST_KEY" ]]; then
    ENV_FILE="${1:-/root/opencurelabs/.env}"
    if [[ -f "$ENV_FILE" ]]; then
        VAST_KEY=$(grep -E '^VAST_AI_KEY=' "$ENV_FILE" 2>/dev/null | cut -d= -f2- | tr -d '"' || true)
    fi
fi

if [[ -z "$VAST_KEY" ]]; then
    echo "  Vast.ai: no API key"
    exit 0
fi

# Query active instances
RESPONSE=$(curl -sf -H "Authorization: Bearer $VAST_KEY" \
    "https://console.vast.ai/api/v0/instances/" 2>/dev/null) || {
    echo "  Vast.ai: API unreachable"
    exit 0
}

# Parse with python (available in venv)
python3 -c "
import json, sys
from datetime import datetime, timezone

data = json.loads(sys.stdin.read())
instances = data.get('instances', data) if isinstance(data, dict) else data

if not isinstance(instances, list):
    instances = []

active = [i for i in instances if i.get('actual_status') in ('running', 'loading')]

if not active:
    print('  Vast.ai: 0 instances')
    sys.exit(0)

total_cost = 0
print(f'  Vast.ai: {len(active)} instance(s)')
for inst in active:
    gpu = inst.get('gpu_name', '?')
    num_gpus = inst.get('num_gpus', 1)
    dph = inst.get('dph_total', 0)
    total_cost += dph
    status = inst.get('actual_status', '?')
    iid = inst.get('id', '?')
    
    # Calculate uptime
    start = inst.get('start_date')
    if start:
        try:
            started = datetime.fromtimestamp(start, tz=timezone.utc)
            delta = datetime.now(tz=timezone.utc) - started
            hours = int(delta.total_seconds() // 3600)
            mins = int((delta.total_seconds() % 3600) // 60)
            uptime = f'{hours}h{mins:02d}m'
        except Exception:
            uptime = '?'
    else:
        uptime = '?'
    
    gpu_label = f'{num_gpus}x {gpu}' if num_gpus > 1 else gpu
    print(f'    #{iid} {gpu_label} | \${dph:.3f}/hr | {uptime} | {status}')

print(f'  Cost: \${total_cost:.3f}/hr (\${total_cost*24:.2f}/day)')
" <<< "$RESPONSE"
