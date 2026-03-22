#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
#  OpenCure Labs — Budget Monitor
#
#  Live view of AI spending across all providers.
#  Auto-refreshes every 30 seconds.
#
#  Displayed in the Zellij "Budget" tab.
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

# Source .env for API keys
if [[ -f "$PROJECT_DIR/.env" ]]; then
    set -a
    # shellcheck source=/dev/null
    source "$PROJECT_DIR/.env"
    set +a
fi

source .venv/bin/activate 2>/dev/null || true

# ── Colors ───────────────────────────────────────────────────────────────────
CYAN='\033[1;96m'   GREEN='\033[1;92m'  YELLOW='\033[1;93m'
RED='\033[1;91m'    DIM='\033[2m'       BOLD='\033[1m'
WHITE='\033[1;97m'  MAGENTA='\033[1;95m'
RESET='\033[0m'

# ── Helpers ──────────────────────────────────────────────────────────────────
divider() {
    echo -e "${DIM}────────────────────────────────────────────────────────────${RESET}"
}

format_cost() {
    python3 -c "v=float('${1:-0}'); print(f'\${v:,.2f}')" 2>/dev/null || echo "\$0.00"
}

# ── Main loop ────────────────────────────────────────────────────────────────
while true; do
    clear
    echo ""
    echo -e "${CYAN}${BOLD}  💰 OpenCure Labs — Budget Monitor${RESET}"
    echo -e "${DIM}  $(date '+%Y-%m-%d %H:%M:%S')  •  refreshes every 30s${RESET}"
    echo ""

    GRAND_TOTAL=0

    # ── 1. Vast.ai ───────────────────────────────────────────────────────
    divider
    echo -e "${YELLOW}${BOLD}  ☁️  Vast.ai — GPU Compute${RESET}"
    echo ""

    VAST_KEY="${VAST_AI_KEY:-}"
    if [[ -n "$VAST_KEY" ]]; then
        # Account balance from API
        API_BALANCE=$(curl -sf -H "Authorization: Bearer $VAST_KEY" \
            "https://console.vast.ai/api/v0/users/current/" 2>/dev/null \
            | python3 -c "import json,sys; print(json.loads(sys.stdin.read()).get('credit',0))" 2>/dev/null \
            || echo "0")

        # Session spend from DB
        VAST_SPENT=$(psql -p 5433 -d opencurelabs -t -A -c \
            "SELECT COALESCE(SUM(total_cost), 0) FROM vast_spend" 2>/dev/null || echo "0")

        # Active instances
        INSTANCE_INFO=$(curl -sf -H "Authorization: Bearer $VAST_KEY" \
            "https://console.vast.ai/api/v0/instances/" 2>/dev/null \
            | python3 -c "
import json, sys
data = json.loads(sys.stdin.read())
instances = data.get('instances', data) if isinstance(data, dict) else data
if not isinstance(instances, list): instances = []
active = [i for i in instances if i.get('actual_status') in ('running', 'loading')]
total_dph = sum(i.get('dph_total', 0) for i in active)
print(f'{len(active)}|{total_dph:.3f}')
for i in active:
    gpu = i.get('gpu_name', '?')
    n = i.get('num_gpus', 1)
    dph = i.get('dph_total', 0)
    st = i.get('actual_status', '?')
    iid = i.get('id', '?')
    label = f'{n}x {gpu}' if n > 1 else gpu
    print(f'  #{iid} {label} | \${dph:.3f}/hr | {st}')
" 2>/dev/null || echo "0|0")

        INST_COUNT="${INSTANCE_INFO%%|*}"
        INST_COST_HR=$(echo "$INSTANCE_INFO" | head -1 | cut -d'|' -f2)

        echo -e "  ${WHITE}Account balance:${RESET}  $(format_cost "$API_BALANCE")"
        echo -e "  ${WHITE}Session spend:${RESET}    $(format_cost "$VAST_SPENT")"
        echo -e "  ${WHITE}Active instances:${RESET}  ${INST_COUNT}"

        # Show instance details if any
        if [[ "$INST_COUNT" != "0" ]]; then
            echo "$INSTANCE_INFO" | tail -n +2 | while read -r line; do
                [[ -n "$line" ]] && echo -e "  ${DIM}$line${RESET}"
            done
            echo -e "  ${WHITE}Burn rate:${RESET}        \$${INST_COST_HR}/hr"
        fi

        GRAND_TOTAL=$(python3 -c "print(float('$GRAND_TOTAL') + float('$VAST_SPENT'))" 2>/dev/null || echo "$GRAND_TOTAL")
    else
        echo -e "  ${DIM}No API key set (VAST_AI_KEY)${RESET}"
    fi

    # ── 2. LLM Providers ────────────────────────────────────────────────
    echo ""
    divider
    echo -e "${MAGENTA}${BOLD}  🧠 LLM Providers${RESET}"
    echo ""

    # Query llm_spend table
    LLM_DATA=$(psql -p 5433 -d opencurelabs -t -A -c "
        SELECT provider,
               SUM(input_tokens) as in_tok,
               SUM(output_tokens) as out_tok,
               SUM(estimated_cost) as cost,
               COUNT(*) as calls
        FROM llm_spend
        GROUP BY provider
        ORDER BY cost DESC
    " 2>/dev/null || echo "")

    LLM_TOTAL=0
    if [[ -n "$LLM_DATA" ]]; then
        printf "  ${WHITE}%-14s %10s %10s %10s %8s${RESET}\n" "Provider" "In Tokens" "Out Tokens" "Cost" "Calls"
        echo -e "  ${DIM}──────────────────────────────────────────────────────${RESET}"
        while IFS='|' read -r provider in_tok out_tok cost calls; do
            [[ -z "$provider" ]] && continue
            COST_FMT=$(format_cost "$cost")
            IN_FMT=$(python3 -c "print(f'{int(float(\"$in_tok\")):,}')" 2>/dev/null || echo "$in_tok")
            OUT_FMT=$(python3 -c "print(f'{int(float(\"$out_tok\")):,}')" 2>/dev/null || echo "$out_tok")
            printf "  %-14s %10s %10s %10s %8s\n" "$provider" "$IN_FMT" "$OUT_FMT" "$COST_FMT" "$calls"
            LLM_TOTAL=$(python3 -c "print(float('$LLM_TOTAL') + float('$cost'))" 2>/dev/null || echo "$LLM_TOTAL")
        done <<< "$LLM_DATA"
        echo ""
        echo -e "  ${WHITE}LLM total:${RESET}  $(format_cost "$LLM_TOTAL")"
    else
        echo -e "  ${DIM}No LLM usage recorded yet.${RESET}"
        echo -e "  ${DIM}Costs will appear here once agent tasks run.${RESET}"
    fi

    GRAND_TOTAL=$(python3 -c "print(float('$GRAND_TOTAL') + float('$LLM_TOTAL'))" 2>/dev/null || echo "$GRAND_TOTAL")

    # ── 3. Summary ──────────────────────────────────────────────────────
    echo ""
    divider
    echo -e "${GREEN}${BOLD}  📊 Session Total${RESET}"
    echo ""
    echo -e "  ${WHITE}${BOLD}$(format_cost "$GRAND_TOTAL")${RESET}"
    echo ""

    # ── Rate cards reference ────────────────────────────────────────────
    echo -e "${DIM}  Rate cards (per 1M tokens):${RESET}"
    echo -e "${DIM}    Gemini 2.5 Flash Lite:  \$0.075 in / \$0.30 out${RESET}"
    echo -e "${DIM}    Claude Opus 4.6:        \$15.00 in / \$75.00 out${RESET}"
    echo -e "${DIM}    Grok (xAI):             \$5.00 in / \$15.00 out${RESET}"
    echo ""

    sleep 30
done
