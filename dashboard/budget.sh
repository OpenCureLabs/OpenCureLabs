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

# PostgreSQL port (override via $POSTGRES_PORT env var)
PG_PORT="${POSTGRES_PORT:-5433}"

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
            | python3 -c "import json,sys; print(f'{json.loads(sys.stdin.read()).get(\"credit\",0):.2f}')" 2>/dev/null \
            || echo "0")

        # Session spend from DB (all-time)
        VAST_SPENT=$(psql -p "$PG_PORT" -d opencurelabs -t -A -c \
            "SELECT COALESCE(SUM(total_cost), 0) FROM vast_spend" 2>/dev/null || echo "0")

        # Per-run spend (filtered by GENESIS_START if set)
        VAST_RUN_SPENT="0"
        if [[ -n "${GENESIS_START:-}" ]]; then
            VAST_RUN_SPENT=$(psql -p "$PG_PORT" -d opencurelabs -t -A -c \
                "SELECT COALESCE(SUM(total_cost), 0) FROM vast_spend WHERE started_at >= to_timestamp($GENESIS_START)" \
                2>/dev/null || echo "0")
        fi

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
        if [[ -n "${GENESIS_START:-}" ]]; then
            echo -e "  ${WHITE}This run:${RESET}         $(format_cost "$VAST_RUN_SPENT")"
        fi
        echo -e "  ${WHITE}All-time spend:${RESET}   $(format_cost "$VAST_SPENT")"
        echo -e "  ${WHITE}Active instances:${RESET}  ${INST_COUNT}"

        # Show instance details if any
        if [[ "$INST_COUNT" != "0" ]]; then
            echo "$INSTANCE_INFO" | tail -n +2 | while read -r line; do
                [[ -n "$line" ]] && echo -e "  ${DIM}$line${RESET}"
            done
            echo -e "  ${WHITE}Burn rate:${RESET}        \$${INST_COST_HR}/hr"
        fi

        GRAND_TOTAL=$(python3 -c "print(float('$GRAND_TOTAL') + float('$VAST_SPENT'))" 2>/dev/null || echo "$GRAND_TOTAL")
        GRAND_RUN_TOTAL=0
        if [[ -n "${GENESIS_START:-}" ]]; then
            GRAND_RUN_TOTAL=$(python3 -c "print(float('$GRAND_RUN_TOTAL') + float('$VAST_RUN_SPENT'))" 2>/dev/null || echo "0")
        fi
    else
        echo -e "  ${DIM}No API key set (VAST_AI_KEY)${RESET}"
    fi

    # ── 2. LLM Providers ────────────────────────────────────────────────
    echo ""
    divider
    echo -e "${MAGENTA}${BOLD}  🧠 LLM Providers${RESET}"
    echo ""

    # Query llm_spend table (all-time)
    LLM_DATA=$(psql -p "$PG_PORT" -d opencurelabs -t -A -c "
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

    # Per-run LLM spend
    LLM_RUN_TOTAL=0
    if [[ -n "${GENESIS_START:-}" ]]; then
        LLM_RUN_TOTAL=$(psql -p "$PG_PORT" -d opencurelabs -t -A -c \
            "SELECT COALESCE(SUM(estimated_cost), 0) FROM llm_spend WHERE created_at >= to_timestamp($GENESIS_START)" \
            2>/dev/null || echo "0")
    fi

    GRAND_TOTAL=$(python3 -c "print(float('$GRAND_TOTAL') + float('$LLM_TOTAL'))" 2>/dev/null || echo "$GRAND_TOTAL")
    if [[ -n "${GENESIS_START:-}" ]]; then
        GRAND_RUN_TOTAL=$(python3 -c "print(float('${GRAND_RUN_TOTAL:-0}') + float('$LLM_RUN_TOTAL'))" 2>/dev/null || echo "${GRAND_RUN_TOTAL:-0}")
    fi

    # ── 3. Summary ──────────────────────────────────────────────────────
    echo ""
    divider
    echo -e "${GREEN}${BOLD}  📊 Totals${RESET}"
    echo ""
    if [[ -n "${GENESIS_START:-}" ]]; then
        RUN_ELAPSED=$(( $(date +%s) - GENESIS_START ))
        RUN_MIN=$(( RUN_ELAPSED / 60 ))
        RUN_SEC=$(( RUN_ELAPSED % 60 ))
        echo -e "  ${WHITE}This run:${RESET}   ${BOLD}$(format_cost "${GRAND_RUN_TOTAL:-0}")${RESET}  ${DIM}(${RUN_MIN}m ${RUN_SEC}s elapsed)${RESET}"
    fi
    echo -e "  ${WHITE}All-time:${RESET}   ${BOLD}$(format_cost "$GRAND_TOTAL")${RESET}"
    echo ""

    # ── 4. Per-Skill Cost Breakdown ─────────────────────────────────────
    SKILL_FILTER=""
    if [[ -n "${GENESIS_START:-}" ]]; then
        SKILL_FILTER="WHERE bj.created_at >= to_timestamp($GENESIS_START)"
        SKILL_LABEL="This Run"
    else
        SKILL_LABEL="All-Time"
    fi

    SKILL_DATA=$(psql -p "$PG_PORT" -d opencurelabs -t -A -c "
        SELECT bj.skill_name,
               COUNT(*) as jobs,
               SUM(CASE WHEN bj.status = 'done' THEN 1 ELSE 0 END) as done,
               SUM(CASE WHEN bj.status = 'failed' THEN 1 ELSE 0 END) as failed,
               COALESCE(SUM(
                   EXTRACT(EPOCH FROM (COALESCE(bj.completed_at, NOW()) - bj.started_at)) / 3600.0
                   * vp.cost_per_hr
               ), 0) as est_cost
        FROM batch_jobs bj
        LEFT JOIN vast_pool vp ON bj.instance_id = vp.instance_id
        $SKILL_FILTER
        GROUP BY bj.skill_name
        ORDER BY est_cost DESC
    " 2>/dev/null || echo "")

    if [[ -n "$SKILL_DATA" ]]; then
        echo ""
        divider
        echo -e "${YELLOW}${BOLD}  🔬 Per-Skill Costs ($SKILL_LABEL)${RESET}"
        echo ""
        printf "  ${WHITE}%-22s %6s %6s %6s %10s${RESET}\n" "Skill" "Jobs" "Done" "Fail" "Est. Cost"
        echo -e "  ${DIM}──────────────────────────────────────────────────────${RESET}"
        while IFS='|' read -r skill jobs done failed est_cost; do
            [[ -z "$skill" ]] && continue
            COST_FMT=$(format_cost "$est_cost")
            printf "  %-22s %6s %6s %6s %10s\n" "$skill" "$jobs" "$done" "$failed" "$COST_FMT"
        done <<< "$SKILL_DATA"
    fi

    # ── 5. Run History ──────────────────────────────────────────────────
    RUN_HISTORY=$(psql -p "$PG_PORT" -d opencurelabs -t -A -c "
        SELECT genesis_run_id,
               COUNT(*) as jobs,
               SUM(CASE WHEN status = 'done' THEN 1 ELSE 0 END) as done,
               SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed,
               MIN(created_at)::text as started,
               COALESCE(SUM(
                   EXTRACT(EPOCH FROM (COALESCE(completed_at, NOW()) - started_at)) / 3600.0
               ), 0) as gpu_hours
        FROM batch_jobs
        WHERE genesis_run_id IS NOT NULL
        GROUP BY genesis_run_id
        ORDER BY MIN(created_at) DESC
        LIMIT 10
    " 2>/dev/null || echo "")

    if [[ -n "$RUN_HISTORY" ]]; then
        echo ""
        divider
        echo -e "${CYAN}${BOLD}  📜 Run History (last 10)${RESET}"
        echo ""
        printf "  ${WHITE}%-26s %6s %6s %6s %10s${RESET}\n" "Run ID" "Jobs" "Done" "Fail" "GPU-hrs"
        echo -e "  ${DIM}──────────────────────────────────────────────────────────${RESET}"
        while IFS='|' read -r run_id jobs done failed started gpu_hours; do
            [[ -z "$run_id" ]] && continue
            GPU_FMT=$(python3 -c "print(f'{float(\"$gpu_hours\"):.2f}')" 2>/dev/null || echo "$gpu_hours")
            printf "  %-26s %6s %6s %6s %10s\n" "$run_id" "$jobs" "$done" "$failed" "$GPU_FMT"
        done <<< "$RUN_HISTORY"
    fi
    echo ""

    # ── Rate cards reference ────────────────────────────────────────────
    echo -e "${DIM}  Rate cards (per 1M tokens):${RESET}"
    echo -e "${DIM}    Gemini 2.5 Flash Lite:  \$0.075 in / \$0.30 out${RESET}"
    echo -e "${DIM}    Claude Opus 4.6:        \$15.00 in / \$75.00 out${RESET}"
    echo -e "${DIM}    Grok (xAI):             \$5.00 in / \$15.00 out${RESET}"
    echo ""

    sleep 30
done
