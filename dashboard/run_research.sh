#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
#  OpenCure Labs — Interactive Research Launcher
#
#  Presents a guided menu for selecting and launching research tasks.
#  Uses Charm's `gum` for beautiful TUI; falls back to bash `select` if missing.
#
#  Usage:
#    bash dashboard/run_research.sh                    # Interactive menu
#    bash dashboard/run_research.sh --task "your task" # CLI bypass (advanced)
#    bash dashboard/run_research.sh --loop              # Continuous mode
#
#  Triggered by Alt+S in the Zellij dashboard.
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail

PROJECT_DIR="/root/opencurelabs"
CONFIG="coordinator/labclaw_workflow.yaml"
LOG="logs/agent.log"

cd "$PROJECT_DIR"
source .venv/bin/activate 2>/dev/null || true

# Source .env for API keys (VAST_AI_KEY, VAST_AI_BUDGET, GENAI_API_KEY, etc.)
if [[ -f "$PROJECT_DIR/.env" ]]; then
    set -a
    # shellcheck source=/dev/null
    source "$PROJECT_DIR/.env"
    set +a
fi

# ── Vast.ai balance helper ────────────────────────────────────────────────────
get_vast_balance() {
    # Query real account credit from Vast.ai API
    local key="${VAST_AI_KEY:-}"
    [[ -z "$key" ]] && echo "0" && return
    curl -sf -H "Authorization: Bearer $key" \
        "https://console.vast.ai/api/v0/users/current/" 2>/dev/null \
    | python3 -c "import json,sys; print(json.loads(sys.stdin.read()).get('credit',0))" 2>/dev/null \
    || echo "0"
}

# ── Colors (for fallback mode) ───────────────────────────────────────────────
CYAN='\033[1;96m'   GREEN='\033[1;92m'  YELLOW='\033[1;93m'
RED='\033[1;91m'    DIM='\033[2m'       BOLD='\033[1m'
RESET='\033[0m'

HAS_GUM=false
command -v gum &>/dev/null && HAS_GUM=true

# ── Task catalog ─────────────────────────────────────────────────────────────
# Each entry:  "Short label|Full task description sent to coordinator"

# Format:  "Menu label ~ Plain explanation|Full task sent to coordinator"

CANCER_TASKS=(
    "Find Tumor Mutations ~ Compare tumor vs healthy DNA to find cancer-causing changes|Identify somatic mutations from tumor/normal paired sequencing data. Run alignment, variant calling with Mutect2, and annotation."
    "Predict Neoantigens ~ Find unique markers the immune system can target|Predict neoantigens from somatic variants and HLA typing. Run the full neoantigen pipeline including HLA typing with OptiType."
    "Map Immune Landscape ~ See which immune cells are present in the tumor|Model the tumor-immune microenvironment from expression data using CIBERSORTx deconvolution and immune cell quantification."
    "Check Data Quality ~ Verify sequencing data is clean before analysis|Run sequencing quality control on cancer genomic data. Check read quality, coverage, and contamination."
    "Predict Protein Shape ~ Use AI to predict 3D structure of a cancer protein|Predict protein structure for a cancer-related target using AlphaFold."
)

DRUG_TASKS=(
    "Train Drug Predictor ~ Build an AI model to predict if a molecule is active|Train a QSAR model on ChEMBL bioactivity data. Compute molecular descriptors with RDKit and train predictive models."
    "Screen Drug Candidates ~ Test thousands of molecules against a target|Run virtual screening via molecular docking. Prepare receptor structure, generate ligand conformers, dock with Vina/Gnina, and rank hits."
    "Optimize a Drug Lead ~ Improve a promising molecule's effectiveness|Optimize a lead compound via iterative docking and QSAR analysis. Predict activity and validate binding poses."
    "Predict Target Shape ~ Use AI to predict 3D structure of a drug target|Predict protein structure for a drug target using AlphaFold to enable docking studies."
)

RARE_TASKS=(
    "Assess Variant Danger ~ Check if a genetic variant causes disease|Analyze variants for pathogenicity and gene-disease associations. Cross-reference ClinVar and OMIM, rank candidate genes."
    "Find New Mutations ~ Find mutations a child has that parents don't|Identify and score de novo variants in trios. Run trio variant calling, inheritance filtering, and pathogenicity scoring."
    "Check Data Quality ~ Verify sequencing data is clean before analysis|Run sequencing quality control on rare disease genomic data. Check read quality, coverage, and contamination."
)

# ── Follow-up prompts ────────────────────────────────────────────────────────
# Ask task-specific questions to collect details the coordinator needs.
# Results are appended to $TASK before sending to the coordinator.
#
# Uses gum if available, otherwise read -rp fallback.

ask_input() {
    local prompt="$1" placeholder="$2" result
    if $HAS_GUM; then
        result=$(gum input \
            --prompt "$prompt " \
            --prompt.foreground 46 \
            --placeholder "$placeholder" \
            --width 80 \
        ) || true
    else
        read -rp "$prompt " result
    fi
    echo "$result"
}

ask_file() {
    local prompt="$1" placeholder="$2" result start_dir="${3:-$PROJECT_DIR/data}"
    if $HAS_GUM; then
        gum style --foreground 242 --italic "  Browse for a file (Enter to select, Esc to skip):" 2>/dev/null || true
        result=$(gum file --all --height 12 "$start_dir" 2>/dev/null) || true
        if [[ -z "$result" ]]; then
            result=$(ask_input "$prompt" "$placeholder")
        fi
    else
        read -rp "$prompt " result
    fi
    echo "$result"
}

# Detect data files in data/ directory
detect_data_files() {
    find "$PROJECT_DIR/data" -type f \
        \( -name "*.vcf" -o -name "*.bam" -o -name "*.fastq*" \
           -o -name "*.csv" -o -name "*.tsv" -o -name "*.sdf" \
           -o -name "*.pdb" -o -name "*.fasta" -o -name "*.fa" \) \
        2>/dev/null || true
}

# Ask for a file only in "my data" mode; returns empty in public mode
ask_data_file() {
    if [[ "${DATA_MODE:-public}" == "mydata" ]]; then
        ask_file "$1" "$2"
    fi
}

# Appends follow-up details to TASK based on SELECTED_LABEL
collect_details() {
    local label="$1"
    local details=""

    # Determine if there are non-file questions for this task
    local has_questions=true
    case "$label" in
        "Find Tumor Mutations"|"Map Immune Landscape"|"Check Data Quality"|"Find New Mutations")
            # File-only tasks: skip entirely in public mode
            [[ "${DATA_MODE:-public}" == "public" ]] && has_questions=false
            ;;
    esac

    if $has_questions; then
        echo ""
        gum style --foreground 39 --italic "A few quick questions so the agent knows what to analyze:" 2>/dev/null \
            || echo -e "${CYAN}A few quick questions so the agent knows what to analyze:${RESET}"
        echo ""
    fi

    case "$label" in
        "Find Tumor Mutations")
            local tumor normal
            tumor=$(ask_data_file "Tumor sample file:" "e.g. data/tumor.bam or data/tumor.vcf")
            normal=$(ask_data_file "Normal (healthy) sample file:" "e.g. data/normal.bam")
            [[ -n "$tumor" ]]  && details+=" Tumor sample: $tumor."
            [[ -n "$normal" ]] && details+=" Normal sample: $normal."
            ;;
        "Predict Neoantigens")
            local vcf hla
            vcf=$(ask_data_file "Somatic variants file:" "e.g. data/somatic.vcf")
            hla=$(ask_input "HLA type (if known, or leave blank):" "e.g. HLA-A*02:01")
            [[ -n "$vcf" ]] && details+=" Variants file: $vcf."
            [[ -n "$hla" ]] && details+=" HLA type: $hla."
            ;;
        "Map Immune Landscape")
            local expr
            expr=$(ask_data_file "Gene expression data file:" "e.g. data/expression.tsv")
            [[ -n "$expr" ]] && details+=" Expression data: $expr."
            ;;
        "Check Data Quality")
            local reads
            reads=$(ask_data_file "Sequencing data file:" "e.g. data/reads.fastq.gz")
            [[ -n "$reads" ]] && details+=" Sequencing data: $reads."
            ;;
        "Predict Protein Shape")
            local gene
            gene=$(ask_input "Gene or protein name:" "e.g. KRAS, TP53, EGFR")
            [[ -n "$gene" ]] && details+=" Target protein: $gene."
            ;;
        "Train Drug Predictor")
            local target
            target=$(ask_input "Drug target or disease:" "e.g. EGFR, breast cancer, CHEMBL203")
            [[ -n "$target" ]] && details+=" Target: $target."
            ;;
        "Screen Drug Candidates")
            local target lib
            target=$(ask_input "Target protein name:" "e.g. EGFR, CDK4, BRAF")
            lib=$(ask_data_file "Compound library (or leave blank for default):" "e.g. data/compounds.sdf")
            [[ -n "$target" ]] && details+=" Target protein: $target."
            [[ -n "$lib" ]]    && details+=" Compound library: $lib."
            ;;
        "Optimize a Drug Lead")
            local smiles target
            smiles=$(ask_input "Compound (SMILES or name):" "e.g. aspirin, CC(=O)Oc1ccccc1C(=O)O")
            target=$(ask_input "Target protein:" "e.g. COX-2, EGFR")
            [[ -n "$smiles" ]] && details+=" Compound: $smiles."
            [[ -n "$target" ]] && details+=" Target: $target."
            ;;
        "Predict Target Shape")
            local gene
            gene=$(ask_input "Gene or protein name:" "e.g. BRAF, ALK, HER2")
            [[ -n "$gene" ]] && details+=" Target protein: $gene."
            ;;
        "Assess Variant Danger")
            local variant
            if [[ "${DATA_MODE:-public}" == "mydata" ]]; then
                variant=$(ask_file "Variant file or ID:" "e.g. data/variants.vcf, rs121913529")
            else
                variant=$(ask_input "Variant (rsID, HGVS, or gene name):" "e.g. rs121913529, BRAF V600E")
            fi
            [[ -n "$variant" ]] && details+=" Variant: $variant."
            ;;
        "Find New Mutations")
            local child parents
            child=$(ask_data_file "Child's sequencing file:" "e.g. data/child.vcf")
            parents=$(ask_data_file "Parents' sequencing files:" "e.g. data/mother.vcf, data/father.vcf")
            [[ -n "$child" ]]   && details+=" Child: $child."
            [[ -n "$parents" ]] && details+=" Parents: $parents."
            ;;
    esac

    # Append details to the task
    if [[ -n "$details" ]]; then
        TASK="$TASK$details"
    fi
}

# ── CLI bypass ───────────────────────────────────────────────────────────────
TASK=""
LOOP_MODE=false
while [[ $# -gt 0 ]]; do
    case "$1" in
        --task) TASK="$2"; shift 2 ;;
        --loop) LOOP_MODE=true; shift ;;
        *) shift ;;
    esac
done

if [[ -n "$TASK" ]]; then
    echo -e "${CYAN}── Running Task ──${RESET}"
    echo -e "${DIM}$TASK${RESET}"
    echo
    nat run --config_file "$CONFIG" --input "$TASK" 2>&1 | tee -a "$LOG"
    echo
    echo -e "${DIM}Press Enter to close${RESET}"
    read -r
    exit 0
fi

# ══════════════════════════════════════════════════════════════════════════════
#  GUM MODE — Beautiful interactive menu
# ══════════════════════════════════════════════════════════════════════════════
if $HAS_GUM; then

    # ── Header ───────────────────────────────────────────────────────────
    gum style \
        --border double \
        --border-foreground 39 \
        --padding "0 2" \
        --margin "0 0" \
        --bold \
        "🧬  OpenCure Labs — Research Launcher"

    echo ""

    # ── Domain selection ─────────────────────────────────────────────────
    DOMAIN=$(gum choose \
        --header "What do you want to research?" \
        --header.foreground 39 \
        --cursor.foreground 46 \
        --item.foreground 255 \
        --selected.foreground 46 \
        --selected.bold \
        "🔬 Cancer — Find mutations, predict immune targets" \
        "💊 Drug Discovery — Screen molecules, predict effectiveness" \
        "🧬 Rare Disease — Analyze genetic variants for diagnosis" \
        "⌨️  Custom Task — Type your own research question" \
        "🚀 Genesis Mode — Run EVERY task across ALL domains (12 runs, full send)" \
    ) || { echo "Cancelled."; read -r; exit 0; }

    echo ""

    # ── Task selection per domain ────────────────────────────────────────
    case "$DOMAIN" in
        *"Cancer"*)
            ITEMS=("${CANCER_TASKS[@]}")
            ;;
        *"Drug"*)
            ITEMS=("${DRUG_TASKS[@]}")
            ;;
        *"Rare"*)
            ITEMS=("${RARE_TASKS[@]}")
            ;;
        *"Custom"*)
            TASK=$(gum input \
                --placeholder "Describe your research task..." \
                --prompt "Task: " \
                --prompt.foreground 46 \
                --width 80 \
                --char-limit 500 \
            ) || { echo "Cancelled."; read -r; exit 0; }

            if [[ -z "$TASK" ]]; then
                echo "No task entered."
                read -r
                exit 0
            fi
            ;;
        *"Genesis"*)
            # ── Genesis Mode ─────────────────────────────────────────────
            # Run EVERY task across ALL domains: 12 runs, full agents, Vast.ai
            ALL_TASKS=()
            ALL_LABELS=()
            ALL_DOMAINS=()
            for t in "${CANCER_TASKS[@]}"; do
                ALL_TASKS+=("${t#*|}")
                ALL_LABELS+=("${t%%|*}")
                ALL_DOMAINS+=("Cancer")
            done
            for t in "${DRUG_TASKS[@]}"; do
                ALL_TASKS+=("${t#*|}")
                ALL_LABELS+=("${t%%|*}")
                ALL_DOMAINS+=("Drug Discovery")
            done
            for t in "${RARE_TASKS[@]}"; do
                ALL_TASKS+=("${t#*|}")
                ALL_LABELS+=("${t%%|*}")
                ALL_DOMAINS+=("Rare Disease")
            done

            TOTAL=${#ALL_TASKS[@]}

            echo ""
            printf '%s\n' \
                "" \
                "  🚀  G E N E S I S   M O D E" \
                "" \
                "  $TOTAL tasks across 3 domains" \
                "  3 agents — continuous until budget exhausted" \
                "  Vast.ai cloud GPU burst — enabled" \
                "  Public databases — TCGA, ClinVar, ChEMBL" \
                "" \
                "  ┌─ Cancer (5 tasks) ──────────────────────┐" \
                "  │  Tumor Mutations · Neoantigens · Immune  │" \
                "  │  Landscape · Data QC · Protein Shape     │" \
                "  ├─ Drug Discovery (4 tasks) ───────────────┤" \
                "  │  Train Predictor · Screen Candidates      │" \
                "  │  Optimize Lead · Target Shape             │" \
                "  ├─ Rare Disease (3 tasks) ──────────────────┤" \
                "  │  Variant Danger · New Mutations · Data QC │" \
                "  └───────────────────────────────────────────┘" \
                "" \
            | gum style \
                --border double \
                --border-foreground 214 \
                --foreground 214 \
                --bold \
                --padding "0 1" \
                --margin "0 0"

            # ── Throughput mode ───────────────────────────────────────
            echo ""
            VAST_INSTANCES=$(gum choose \
                --header "Execution mode:" \
                --header.foreground 214 \
                --cursor.foreground 46 \
                --item.foreground 252 \
                --selected.foreground 46 \
                --selected.bold \
                "1 — Sequential (safest, lowest cost)" \
                "3 — Fast parallel" \
                "6 — Max throughput" \
                "12 — All at once" \
                "100 — Batch mode (Vast.ai pool)" \
            ) || { echo "Cancelled."; read -r; exit 0; }
            PARALLEL="${VAST_INSTANCES%%[[:space:]]*}"
            if [[ $PARALLEL -eq 100 ]]; then
                MODE_LABEL="batch (10 instances)"
                BATCH_MODE=1
            else
                BATCH_MODE=0
                [[ $PARALLEL -eq 1 ]] && MODE_LABEL="sequential" || MODE_LABEL="$PARALLEL parallel"
            fi

            # ── Budget display (pull from Vast.ai account) ────────────────
            API_BALANCE=$(get_vast_balance)
            ENV_CAP="${VAST_AI_BUDGET:-0}"
            # Use API balance; VAST_AI_BUDGET as optional cap
            if [[ "$ENV_CAP" != "0" ]] && [[ -n "$ENV_CAP" ]]; then
                VAST_BUDGET=$(python3 -c "print(min(float('$ENV_CAP'), float('$API_BALANCE')))" 2>/dev/null || echo "$ENV_CAP")
            else
                VAST_BUDGET="$API_BALANCE"
            fi
            echo ""
            if python3 -c "exit(0 if float('$VAST_BUDGET') > 0 else 1)" 2>/dev/null; then
                VAST_SPENT=$(psql -p 5433 -d opencurelabs -t -A -c \
                    "SELECT COALESCE(SUM(total_cost), 0) FROM vast_spend" 2>/dev/null || echo "0")
                VAST_REMAINING=$(python3 -c "print(f'{max(0, float(\"$VAST_BUDGET\") - float(\"$VAST_SPENT\")):.2f}')" 2>/dev/null || echo "?")
                gum style --foreground 214 \
                    "  💰 Vast.ai balance: \$$API_BALANCE — budget: \$$VAST_BUDGET (spent: \$$VAST_SPENT)"
                gum style --foreground 46 \
                    "  🔄 Continuous mode — loops until budget exhausted"
            else
                gum style --foreground 196 \
                    "  ⚠️  No Vast.ai balance or budget — will run once"
            fi

            echo ""
            gum confirm "Launch Genesis Mode? ($TOTAL tasks, $MODE_LABEL, continuous)" \
                --affirmative "🚀 SEND IT" --negative "Cancel" \
                || { echo "Cancelled."; read -r; exit 0; }

            # ── Genesis Continuous Loop ───────────────────────────────────
            echo ""
            gum style --foreground 214 --bold "🚀 Genesis Mode activated — $TOTAL tasks, $MODE_LABEL, continuous"
            echo ""

            GENESIS_TOTAL_OK=0
            GENESIS_TOTAL_FAILED=0
            GENESIS_START=$(date +%s)
            ROUND=0

            export LABCLAW_COMPUTE=vast_ai

            # ── BATCH MODE: dispatch to Vast.ai instance pool ─────────────
            if [[ "${BATCH_MODE:-0}" -eq 1 ]]; then
                BATCH_COUNT=$(gum input \
                    --header "How many tasks?" \
                    --placeholder "100" \
                    --value "100" \
                    --header.foreground 214 \
                    --prompt.foreground 46 \
                ) || BATCH_COUNT=100

                POOL_SIZE=$(gum input \
                    --header "Instance pool size?" \
                    --placeholder "10" \
                    --value "10" \
                    --header.foreground 214 \
                    --prompt.foreground 46 \
                ) || POOL_SIZE=10

                echo ""
                gum style --foreground 214 --bold \
                    "  📦 Batch dispatch: $BATCH_COUNT tasks → $POOL_SIZE Vast.ai instances"
                echo ""

                BATCH_LOG="$PROJECT_DIR/logs/batch-$(date +%Y%m%d-%H%M%S).log"
                python3 -m agentiq_labclaw.compute.batch_dispatcher \
                    --count "$BATCH_COUNT" \
                    --pool-size "$POOL_SIZE" \
                    --max-cost 0.50 \
                    --config "$PROJECT_DIR/config/research_tasks.yaml" \
                    2>&1 | tee "$BATCH_LOG"

                export LABCLAW_COMPUTE=local
                echo ""
                gum style --foreground 214 "  📋 Batch log: $BATCH_LOG"
                echo ""
                gum style --foreground 242 "Press Enter to close"
                read -r
                exit 0
            fi

            while true; do
                ROUND=$((ROUND + 1))

                # ── Budget check before each round ───────────────────
                if python3 -c "exit(0 if float('$VAST_BUDGET') > 0 else 1)" 2>/dev/null; then
                    VAST_SPENT=$(psql -p 5433 -d opencurelabs -t -A -c \
                        "SELECT COALESCE(SUM(total_cost), 0) FROM vast_spend" 2>/dev/null || echo "0")
                    VAST_REMAINING=$(python3 -c "print(f'{max(0, float(\"$VAST_BUDGET\") - float(\"$VAST_SPENT\")):.2f}')" 2>/dev/null || echo "0")
                    if python3 -c "exit(0 if float('$VAST_REMAINING') <= 0 else 1)" 2>/dev/null; then
                        echo ""
                        gum style --foreground 196 --bold \
                            "  💰 Budget exhausted! Spent: \$$VAST_SPENT / \$$VAST_BUDGET"
                        break
                    fi
                    gum style --foreground 214 \
                        "  💰 Round $ROUND — \$$VAST_REMAINING remaining of \$$VAST_BUDGET"
                else
                    # No budget/balance — run only one round
                    if [[ $ROUND -gt 1 ]]; then
                        break
                    fi
                fi

                GENESIS_LOG_DIR="$PROJECT_DIR/logs/genesis-$(date +%Y%m%d-%H%M%S)"
                mkdir -p "$GENESIS_LOG_DIR"

                ROUND_OK=0
                ROUND_FAILED=0

                if [[ $PARALLEL -le 1 ]]; then
                    # ── Sequential execution ─────────────────────────
                    for i in $(seq 0 $((TOTAL - 1))); do
                        TASK_NUM=$((i + 1))
                        RAW_LABEL="${ALL_LABELS[$i]}"
                        LABEL="${RAW_LABEL%% ~*}"
                        DOMAIN_NAME="${ALL_DOMAINS[$i]}"
                        GENESIS_TASK="${ALL_TASKS[$i]} Use public databases (TCGA/ClinVar/ChEMBL) for data sourcing. Deploy 3 parallel agents. Use Vast.ai cloud GPU for compute."
                        TASK_LOG="$GENESIS_LOG_DIR/task-${TASK_NUM}-$(echo "$LABEL" | tr ' ' '_').log"

                        gum style --foreground 214 --bold \
                            "  ▶ [R${ROUND} ${TASK_NUM}/$TOTAL] $DOMAIN_NAME → $LABEL"

                        if nat run --config_file "$CONFIG" --input "$GENESIS_TASK" \
                            >>"$TASK_LOG" 2>&1; then
                            ROUND_OK=$((ROUND_OK + 1))
                            gum style --foreground 46 "  ✅ [R${ROUND} ${TASK_NUM}/$TOTAL] $LABEL — complete"
                        else
                            ROUND_FAILED=$((ROUND_FAILED + 1))
                            gum style --foreground 196 "  ❌ [R${ROUND} ${TASK_NUM}/$TOTAL] $LABEL — failed (see $TASK_LOG)"
                        fi
                        echo ""
                    done
                else
                    # ── Parallel batch execution ─────────────────────
                    TASK_IDX=0
                    while [[ $TASK_IDX -lt $TOTAL ]]; do
                        BATCH_PIDS=()
                        BATCH_LABELS=()
                        BATCH_LOGS=()
                        BATCH_END=$((TASK_IDX + PARALLEL))
                        [[ $BATCH_END -gt $TOTAL ]] && BATCH_END=$TOTAL

                        for i in $(seq $TASK_IDX $((BATCH_END - 1))); do
                            TASK_NUM=$((i + 1))
                            RAW_LABEL="${ALL_LABELS[$i]}"
                            LABEL="${RAW_LABEL%% ~*}"
                            DOMAIN_NAME="${ALL_DOMAINS[$i]}"
                            GENESIS_TASK="${ALL_TASKS[$i]} Use public databases (TCGA/ClinVar/ChEMBL) for data sourcing. Deploy 3 parallel agents. Use Vast.ai cloud GPU for compute."
                            TASK_LOG="$GENESIS_LOG_DIR/task-${TASK_NUM}-$(echo "$LABEL" | tr ' ' '_').log"

                            gum style --foreground 214 --bold \
                                "  ▶ [R${ROUND} ${TASK_NUM}/$TOTAL] $DOMAIN_NAME → $LABEL"

                            ( nat run --config_file "$CONFIG" --input "$GENESIS_TASK" \
                                >>"$TASK_LOG" 2>&1 ) &
                            BATCH_PIDS+=($!)
                            BATCH_LABELS+=("$LABEL")
                            BATCH_LOGS+=("$TASK_LOG")
                        done

                        BATCH_SIZE=${#BATCH_PIDS[@]}
                        echo ""
                        gum style --foreground 242 \
                            "  ⏳ Waiting for batch of $BATCH_SIZE tasks..."
                        echo ""

                        for j in $(seq 0 $((BATCH_SIZE - 1))); do
                            PID="${BATCH_PIDS[$j]}"
                            LABEL="${BATCH_LABELS[$j]}"
                            GLOBAL_NUM=$((TASK_IDX + j + 1))

                            if wait "$PID" 2>/dev/null; then
                                ROUND_OK=$((ROUND_OK + 1))
                                gum style --foreground 46 "  ✅ [R${ROUND} ${GLOBAL_NUM}/$TOTAL] $LABEL — complete"
                            else
                                ROUND_FAILED=$((ROUND_FAILED + 1))
                                gum style --foreground 196 "  ❌ [R${ROUND} ${GLOBAL_NUM}/$TOTAL] $LABEL — failed (see ${BATCH_LOGS[$j]})"
                            fi
                        done

                        TASK_IDX=$BATCH_END
                        [[ $TASK_IDX -lt $TOTAL ]] && echo ""
                    done
                fi

                GENESIS_TOTAL_OK=$((GENESIS_TOTAL_OK + ROUND_OK))
                GENESIS_TOTAL_FAILED=$((GENESIS_TOTAL_FAILED + ROUND_FAILED))

                echo ""
                gum style --foreground 214 \
                    "  📋 Round $ROUND complete: $ROUND_OK passed, $ROUND_FAILED failed"
                echo ""
            done

            export LABCLAW_COMPUTE=local

            # ── Genesis Summary ──────────────────────────────────────────
            GENESIS_END=$(date +%s)
            GENESIS_ELAPSED=$(( GENESIS_END - GENESIS_START ))
            GENESIS_MIN=$(( GENESIS_ELAPSED / 60 ))
            GENESIS_SEC=$(( GENESIS_ELAPSED % 60 ))

            # Get spend from DB
            GENESIS_SPENT=$(psql -p 5433 -d opencurelabs -t -A -c \
                "SELECT COALESCE(SUM(total_cost), 0) FROM vast_spend WHERE started_at >= to_timestamp($GENESIS_START)" \
                2>/dev/null || echo "?")

            echo ""
            printf '%s\n' \
                "" \
                "  🚀 GENESIS COMPLETE" \
                "" \
                "  🔄 Rounds:  $ROUND" \
                "  ✅ Passed:  $GENESIS_TOTAL_OK" \
                "  ❌ Failed:  $GENESIS_TOTAL_FAILED" \
                "  ⏱  Time:    ${GENESIS_MIN}m ${GENESIS_SEC}s" \
                "  💰 Spent:   \$$GENESIS_SPENT" \
                "  📁 Logs:    $PROJECT_DIR/logs/genesis-*" \
                "" \
            | gum style \
                --border double \
                --border-foreground "$( [[ $GENESIS_TOTAL_FAILED -eq 0 ]] && echo 46 || echo 196 )" \
                --foreground "$( [[ $GENESIS_TOTAL_FAILED -eq 0 ]] && echo 46 || echo 214 )" \
                --bold \
                --padding "0 2" \
                --margin "0 0"

            echo ""
            echo -e "${DIM}Press Enter to close${RESET}"
            read -r
            exit 0
            ;;
    esac

    # If not custom, show task chooser
    if [[ -z "$TASK" ]]; then
        # Build display labels:  "Label — explanation"
        DISPLAY=()
        for item in "${ITEMS[@]}"; do
            raw="${item%%|*}"           # "Label ~ explanation"
            label="${raw%% ~*}"         # "Label"
            desc="${raw#*~ }"           # "explanation"
            DISPLAY+=("$label — $desc")
        done

        SELECTED=$(gum choose \
            --header "Select task:" \
            --header.foreground 39 \
            --cursor.foreground 46 \
            --item.foreground 252 \
            --selected.foreground 46 \
            --selected.bold \
            "${DISPLAY[@]}" \
        ) || { echo "Cancelled."; read -r; exit 0; }

        # Extract the label part (before " — ") and find matching task
        SELECTED_LABEL="${SELECTED%% — *}"
        for item in "${ITEMS[@]}"; do
            raw="${item%%|*}"
            label="${raw%% ~*}"
            if [[ "$label" == "$SELECTED_LABEL" ]]; then
                TASK="${item#*|}"
                break
            fi
        done
    fi

    # ── Data mode selection ──────────────────────────────────────────
    DATA_MODE="public"
    DATA_FILES=$(detect_data_files)
    FILE_COUNT=0
    [[ -n "$DATA_FILES" ]] && FILE_COUNT=$(echo "$DATA_FILES" | wc -l)

    echo ""
    if [[ "$FILE_COUNT" -gt 0 ]]; then
        gum style --foreground 242 --italic \
            "📂 Found $FILE_COUNT data file(s) in data/"
    else
        gum style --foreground 242 --italic \
            "📂 No data files in data/ yet"
    fi
    echo ""

    DATA_MODE_CHOICE=$(gum choose \
        --header "Where should the data come from?" \
        --header.foreground 39 \
        --cursor.foreground 46 \
        --item.foreground 255 \
        --selected.foreground 46 \
        --selected.bold \
        "🌐 Public databases — Search TCGA, ClinVar, ChEMBL automatically" \
        "📁 My data — Use files I've uploaded to data/" \
    ) || { echo "Cancelled."; read -r; exit 0; }

    case "$DATA_MODE_CHOICE" in
        *"Public"*)  DATA_MODE="public" ;;
        *"My data"*) DATA_MODE="mydata" ;;
    esac

    # ── Follow-up questions ──────────────────────────────────────────
    if [[ -n "${SELECTED_LABEL:-}" ]]; then
        collect_details "$SELECTED_LABEL"
    fi

    # ── Agent count ──────────────────────────────────────────────────
    echo ""
    AGENT_COUNT=$(gum choose \
        --header "How many agents should work on this?" \
        --header.foreground 39 \
        --cursor.foreground 46 \
        --item.foreground 252 \
        --selected.foreground 46 \
        --selected.bold \
        "1 agent  — Simple, sequential analysis" \
        "2 agents — Moderate parallelism" \
        "3 agents — Full parallelism" \
    ) || { echo "Cancelled."; read -r; exit 0; }

    AGENT_NUM="${AGENT_COUNT%%[[:space:]]*}"

    # ── Vast.ai burst (compute-heavy tasks) ──────────────────────────
    USE_VAST="no"
    case "${SELECTED_LABEL:-}" in
        "Train Drug Predictor"|"Screen Drug Candidates"|"Predict Protein Shape"|"Predict Target Shape")
            echo ""
            if gum confirm "Use cloud GPU (Vast.ai) for faster results?" \
                --affirmative "Yes, use cloud" --negative "No, local GPU"; then
                USE_VAST="yes"
            fi
            ;;
    esac

    # ── Append options to task ───────────────────────────────────────
    [[ "$DATA_MODE" == "public" ]] && TASK="$TASK Use public databases (TCGA/ClinVar/ChEMBL) for data sourcing."
    [[ "${AGENT_NUM:-1}" -gt 1 ]] 2>/dev/null && TASK="$TASK Deploy $AGENT_NUM parallel agents."
    [[ "$USE_VAST" == "yes" ]] && TASK="$TASK Use Vast.ai cloud GPU for compute."

    # ── Confirmation ─────────────────────────────────────────────────────
    echo ""
    printf '%s\n' \
        "📋 Task: $TASK" \
        "$([[ "$DATA_MODE" == "public" ]] && echo "📡 Data: Public databases" || echo "📁 Data: My files")" \
        "🤖 Agents: ${AGENT_NUM:-1}" \
        "$([[ "$USE_VAST" == "yes" ]] && echo "☁️  Compute: Vast.ai cloud GPU" || echo "🖥️  Compute: Local GPU")" \
    | gum style \
        --border rounded \
        --border-foreground 46 \
        --padding "0 2" \
        --margin "0 0" \
        --foreground 255

    # ── Run mode ─────────────────────────────────────────────────────────
    if ! $LOOP_MODE; then
        echo ""
        RUN_MODE=$(gum choose \
            --header "How should this run?" \
            --header.foreground 39 \
            --cursor.foreground 46 \
            --item.foreground 252 \
            --selected.foreground 46 \
            --selected.bold \
            "▶ Run once — Execute and stop" \
            "🔁 Run continuously — Keep re-running until stopped" \
        ) || { echo "Cancelled."; read -r; exit 0; }

        case "$RUN_MODE" in
            *"continuously"*) LOOP_MODE=true ;;
        esac
    fi

    echo ""
    gum confirm "Launch this research task?" --affirmative "Run" --negative "Cancel" \
        || { echo "Cancelled."; read -r; exit 0; }

    # ── Launch ───────────────────────────────────────────────────────────
    [[ "$USE_VAST" == "yes" ]] && export LABCLAW_COMPUTE=vast_ai || export LABCLAW_COMPUTE=local

    RUN_COUNT=0
    while true; do
        RUN_COUNT=$((RUN_COUNT + 1))
        echo ""
        if $LOOP_MODE; then
            gum style --foreground 46 --bold "▶ Run #$RUN_COUNT — Launching research pipeline..."
        else
            gum style --foreground 46 --bold "▶ Launching research pipeline..."
        fi
        echo ""

        nat run --config_file "$CONFIG" --input "$TASK" 2>&1 | tee -a "$LOG"

        echo ""
        gum style --foreground 46 "✅ Run #$RUN_COUNT complete."

        if ! $LOOP_MODE; then
            echo ""
            echo -e "${DIM}Press Enter to close${RESET}"
            read -r
            break
        fi

        # Continuous mode: countdown with abort option
        echo ""
        gum style --foreground 214 --bold "🔁 Continuous mode — next run in 10 seconds"
        gum style --foreground 242 "Press Ctrl+C to stop, or wait to continue..."
        echo ""

        # Countdown with gum spin
        if ! gum spin --spinner dot --title "Waiting 10s before next run..." -- sleep 10; then
            echo ""
            gum style --foreground 46 "⏹ Stopped after $RUN_COUNT run(s)."
            echo ""
            echo -e "${DIM}Press Enter to close${RESET}"
            read -r
            break
        fi
    done
    exit 0
fi

# ══════════════════════════════════════════════════════════════════════════════
#  FALLBACK MODE — Bash select menu (no gum installed)
# ══════════════════════════════════════════════════════════════════════════════
echo -e "${CYAN}══════════════════════════════════════════════════${RESET}"
echo -e "${CYAN}  🧬 OpenCure Labs — Research Launcher${RESET}"
echo -e "${CYAN}══════════════════════════════════════════════════${RESET}"
echo ""
echo -e "${BOLD}What do you want to research?${RESET}"
echo ""

DOMAINS=("Cancer — Find mutations, predict immune targets" "Drug Discovery — Screen molecules, predict effectiveness" "Rare Disease — Analyze genetic variants for diagnosis" "Custom Task — Type your own question" "Genesis Mode — Run EVERY task across ALL domains (12 runs)")
select domain in "${DOMAINS[@]}"; do
    case "$REPLY" in
        1) ITEMS=("${CANCER_TASKS[@]}"); break ;;
        2) ITEMS=("${DRUG_TASKS[@]}"); break ;;
        3) ITEMS=("${RARE_TASKS[@]}"); break ;;
        4)
            echo ""
            read -rp "Task: " TASK
            if [[ -z "$TASK" ]]; then
                echo "No task entered."
                read -r
                exit 0
            fi
            ITEMS=()
            break
            ;;
        5)
            # ── Genesis Mode (Fallback) ──────────────────────────────
            ALL_TASKS=()
            ALL_LABELS=()
            ALL_DOMAINS=()
            for t in "${CANCER_TASKS[@]}"; do
                ALL_TASKS+=("${t#*|}")
                raw="${t%%|*}"; ALL_LABELS+=("${raw%% ~*}")
                ALL_DOMAINS+=("Cancer")
            done
            for t in "${DRUG_TASKS[@]}"; do
                ALL_TASKS+=("${t#*|}")
                raw="${t%%|*}"; ALL_LABELS+=("${raw%% ~*}")
                ALL_DOMAINS+=("Drug Discovery")
            done
            for t in "${RARE_TASKS[@]}"; do
                ALL_TASKS+=("${t#*|}")
                raw="${t%%|*}"; ALL_LABELS+=("${raw%% ~*}")
                ALL_DOMAINS+=("Rare Disease")
            done
            TOTAL=${#ALL_TASKS[@]}

            echo ""
            echo -e "${YELLOW}══════════════════════════════════════════════════${RESET}"
            echo -e "${YELLOW}  🚀 G E N E S I S   M O D E${RESET}"
            echo -e "${YELLOW}══════════════════════════════════════════════════${RESET}"
            echo -e "  $TOTAL tasks · 3 domains · 3 agents · Vast.ai burst"
            echo ""

            echo -e "${BOLD}Execution mode:${RESET}"
            PARALLEL_OPTS=("1 — Sequential" "3 — Fast parallel" "6 — Max throughput" "12 — All at once" "100 — Batch mode (Vast.ai pool)")
            select po in "${PARALLEL_OPTS[@]}"; do
                case "$REPLY" in
                    1) PARALLEL=1; break ;; 2) PARALLEL=3; break ;;
                    3) PARALLEL=6; break ;; 4) PARALLEL=12; break ;;
                    5) PARALLEL=100; break ;;
                    *) echo "Invalid choice." ;;
                esac
            done
            if [[ $PARALLEL -eq 100 ]]; then
                MODE_LABEL="batch (10 instances)"
                BATCH_MODE=1
            else
                BATCH_MODE=0
                [[ $PARALLEL -eq 1 ]] && MODE_LABEL="sequential" || MODE_LABEL="$PARALLEL parallel"
            fi

            API_BALANCE=$(get_vast_balance)
            ENV_CAP="${VAST_AI_BUDGET:-0}"
            if [[ "$ENV_CAP" != "0" ]] && [[ -n "$ENV_CAP" ]]; then
                VAST_BUDGET=$(python3 -c "print(min(float('$ENV_CAP'), float('$API_BALANCE')))" 2>/dev/null || echo "$ENV_CAP")
            else
                VAST_BUDGET="$API_BALANCE"
            fi
            if python3 -c "exit(0 if float('$VAST_BUDGET') > 0 else 1)" 2>/dev/null; then
                VAST_SPENT=$(psql -p 5433 -d opencurelabs -t -A -c \
                    "SELECT COALESCE(SUM(total_cost), 0) FROM vast_spend" 2>/dev/null || echo "0")
                echo -e "  💰 Vast.ai balance: \$$API_BALANCE — budget: \$$VAST_BUDGET (spent: \$$VAST_SPENT)"
                echo -e "  🔄 Continuous — loops until budget exhausted"
            else
                echo -e "${RED}  ⚠️  No Vast.ai balance or budget — will run once${RESET}"
            fi

            echo ""
            read -rp "Launch Genesis Mode? ($TOTAL tasks, $MODE_LABEL, continuous) [y/N] " genesis_confirm
            case "$genesis_confirm" in
                [yY]*)
                    GENESIS_TOTAL_OK=0
                    GENESIS_TOTAL_FAILED=0
                    GENESIS_START=$(date +%s)
                    ROUND=0

                    export LABCLAW_COMPUTE=vast_ai

                    # ── BATCH MODE: dispatch to Vast.ai instance pool ────
                    if [[ "${BATCH_MODE:-0}" -eq 1 ]]; then
                        echo ""
                        read -rp "How many tasks? [100] " BATCH_COUNT
                        BATCH_COUNT="${BATCH_COUNT:-100}"
                        read -rp "Instance pool size? [10] " POOL_SIZE
                        POOL_SIZE="${POOL_SIZE:-10}"

                        echo ""
                        echo -e "${YELLOW}  📦 Batch dispatch: $BATCH_COUNT tasks → $POOL_SIZE Vast.ai instances${RESET}"
                        echo ""

                        BATCH_LOG="$PROJECT_DIR/logs/batch-$(date +%Y%m%d-%H%M%S).log"
                        python3 -m agentiq_labclaw.compute.batch_dispatcher \
                            --count "$BATCH_COUNT" \
                            --pool-size "$POOL_SIZE" \
                            --max-cost 0.50 \
                            --config "$PROJECT_DIR/config/research_tasks.yaml" \
                            2>&1 | tee "$BATCH_LOG"

                        export LABCLAW_COMPUTE=local
                        echo ""
                        echo -e "${YELLOW}  📋 Batch log: $BATCH_LOG${RESET}"
                        echo ""
                        echo -e "${DIM}Press Enter to close${RESET}"
                        read -r
                        exit 0
                    fi

                    while true; do
                        ROUND=$((ROUND + 1))

                        # Budget check before each round
                        if python3 -c "exit(0 if float('$VAST_BUDGET') > 0 else 1)" 2>/dev/null; then
                            VAST_SPENT=$(psql -p 5433 -d opencurelabs -t -A -c \
                                "SELECT COALESCE(SUM(total_cost), 0) FROM vast_spend" 2>/dev/null || echo "0")
                            VAST_REMAINING=$(python3 -c "print(f'{max(0, float(\"$VAST_BUDGET\") - float(\"$VAST_SPENT\")):.2f}')" 2>/dev/null || echo "0")
                            if python3 -c "exit(0 if float('$VAST_REMAINING') <= 0 else 1)" 2>/dev/null; then
                                echo ""
                                echo -e "${RED}  💰 Budget exhausted! Spent: \$$VAST_SPENT / \$$VAST_BUDGET${RESET}"
                                break
                            fi
                            echo -e "${YELLOW}  💰 Round $ROUND — \$$VAST_REMAINING remaining of \$$VAST_BUDGET${RESET}"
                        else
                            if [[ $ROUND -gt 1 ]]; then
                                break
                            fi
                        fi

                        GENESIS_LOG_DIR="$PROJECT_DIR/logs/genesis-$(date +%Y%m%d-%H%M%S)"
                        mkdir -p "$GENESIS_LOG_DIR"

                        ROUND_OK=0
                        ROUND_FAILED=0

                        if [[ $PARALLEL -le 1 ]]; then
                            for i in $(seq 0 $((TOTAL - 1))); do
                                TASK_NUM=$((i + 1))
                                LABEL="${ALL_LABELS[$i]}"
                                DOMAIN_NAME="${ALL_DOMAINS[$i]}"
                                GENESIS_TASK="${ALL_TASKS[$i]} Use public databases (TCGA/ClinVar/ChEMBL) for data sourcing. Deploy 3 parallel agents. Use Vast.ai cloud GPU for compute."
                                TASK_LOG="$GENESIS_LOG_DIR/task-${TASK_NUM}-$(echo "$LABEL" | tr ' ' '_').log"

                                echo -e "${YELLOW}  ▶ [R${ROUND} ${TASK_NUM}/$TOTAL] $DOMAIN_NAME → $LABEL${RESET}"

                                if nat run --config_file "$CONFIG" --input "$GENESIS_TASK" \
                                    >>"$TASK_LOG" 2>&1; then
                                    ROUND_OK=$((ROUND_OK + 1))
                                    echo -e "${GREEN}  ✅ [R${ROUND} ${TASK_NUM}/$TOTAL] $LABEL — complete${RESET}"
                                else
                                    ROUND_FAILED=$((ROUND_FAILED + 1))
                                    echo -e "${RED}  ❌ [R${ROUND} ${TASK_NUM}/$TOTAL] $LABEL — failed (see $TASK_LOG)${RESET}"
                                fi
                                echo ""
                            done
                        else
                            TASK_IDX=0
                            while [[ $TASK_IDX -lt $TOTAL ]]; do
                                BATCH_PIDS=()
                                BATCH_LABELS=()
                                BATCH_LOGS=()
                                BATCH_END=$((TASK_IDX + PARALLEL))
                                [[ $BATCH_END -gt $TOTAL ]] && BATCH_END=$TOTAL

                                for i in $(seq $TASK_IDX $((BATCH_END - 1))); do
                                    TASK_NUM=$((i + 1))
                                    LABEL="${ALL_LABELS[$i]}"
                                    DOMAIN_NAME="${ALL_DOMAINS[$i]}"
                                    GENESIS_TASK="${ALL_TASKS[$i]} Use public databases (TCGA/ClinVar/ChEMBL) for data sourcing. Deploy 3 parallel agents. Use Vast.ai cloud GPU for compute."
                                    TASK_LOG="$GENESIS_LOG_DIR/task-${TASK_NUM}-$(echo "$LABEL" | tr ' ' '_').log"

                                    echo -e "${YELLOW}  ▶ [R${ROUND} ${TASK_NUM}/$TOTAL] $DOMAIN_NAME → $LABEL${RESET}"
                                    ( nat run --config_file "$CONFIG" --input "$GENESIS_TASK" >>"$TASK_LOG" 2>&1 ) &
                                    BATCH_PIDS+=($!)
                                    BATCH_LABELS+=("$LABEL")
                                    BATCH_LOGS+=("$TASK_LOG")
                                done

                                BATCH_SIZE=${#BATCH_PIDS[@]}
                                echo ""
                                echo -e "${DIM}  ⏳ Waiting for batch of $BATCH_SIZE tasks...${RESET}"
                                echo ""

                                for j in $(seq 0 $((BATCH_SIZE - 1))); do
                                    PID="${BATCH_PIDS[$j]}"
                                    LABEL="${BATCH_LABELS[$j]}"
                                    GLOBAL_NUM=$((TASK_IDX + j + 1))
                                    if wait "$PID" 2>/dev/null; then
                                        ROUND_OK=$((ROUND_OK + 1))
                                        echo -e "${GREEN}  ✅ [R${ROUND} ${GLOBAL_NUM}/$TOTAL] $LABEL — complete${RESET}"
                                    else
                                        ROUND_FAILED=$((ROUND_FAILED + 1))
                                        echo -e "${RED}  ❌ [R${ROUND} ${GLOBAL_NUM}/$TOTAL] $LABEL — failed (see ${BATCH_LOGS[$j]})${RESET}"
                                    fi
                                done

                                TASK_IDX=$BATCH_END
                                [[ $TASK_IDX -lt $TOTAL ]] && echo ""
                            done
                        fi

                        GENESIS_TOTAL_OK=$((GENESIS_TOTAL_OK + ROUND_OK))
                        GENESIS_TOTAL_FAILED=$((GENESIS_TOTAL_FAILED + ROUND_FAILED))

                        echo ""
                        echo -e "${YELLOW}  📋 Round $ROUND complete: $ROUND_OK passed, $ROUND_FAILED failed${RESET}"
                        echo ""
                    done

                    export LABCLAW_COMPUTE=local

                    GENESIS_END=$(date +%s)
                    GENESIS_ELAPSED=$(( GENESIS_END - GENESIS_START ))
                    GENESIS_MIN=$(( GENESIS_ELAPSED / 60 ))
                    GENESIS_SEC=$(( GENESIS_ELAPSED % 60 ))

                    GENESIS_SPENT=$(psql -p 5433 -d opencurelabs -t -A -c \
                        "SELECT COALESCE(SUM(total_cost), 0) FROM vast_spend WHERE started_at >= to_timestamp($GENESIS_START)" \
                        2>/dev/null || echo "?")

                    echo ""
                    echo -e "${YELLOW}══════════════════════════════════════════════════${RESET}"
                    echo -e "${YELLOW}  🚀 GENESIS COMPLETE${RESET}"
                    echo -e "  🔄 Rounds:  $ROUND"
                    echo -e "  ✅ Passed:  $GENESIS_TOTAL_OK"
                    echo -e "  ❌ Failed:  $GENESIS_TOTAL_FAILED"
                    echo -e "  ⏱  Time:    ${GENESIS_MIN}m ${GENESIS_SEC}s"
                    echo -e "  💰 Spent:   \$$GENESIS_SPENT"
                    echo -e "${YELLOW}══════════════════════════════════════════════════${RESET}"
                    echo ""
                    echo -e "${DIM}Press Enter to close${RESET}"
                    read -r
                    exit 0
                    ;;
                *)
                    echo "Cancelled."
                    read -r
                    exit 0
                    ;;
            esac
            ;;
        *) echo "Invalid choice. Try again." ;;
    esac
done

# If not custom, show task menu
if [[ -z "${TASK:-}" ]]; then
    echo ""
    echo -e "${BOLD}Select task:${RESET}"
    echo ""

    DISPLAY=()
    for item in "${ITEMS[@]}"; do
        raw="${item%%|*}"
        label="${raw%% ~*}"
        desc="${raw#*~ }"
        DISPLAY+=("$label — $desc")
    done

    select entry in "${DISPLAY[@]}"; do
        if [[ -n "$entry" ]]; then
            SELECTED_LABEL="${entry%% — *}"
            for item in "${ITEMS[@]}"; do
                raw="${item%%|*}"
                label="${raw%% ~*}"
                if [[ "$label" == "$SELECTED_LABEL" ]]; then
                    TASK="${item#*|}"
                    break 2
                fi
            done
        fi
        echo "Invalid choice. Try again."
    done

fi

# ── Data mode ────────────────────────────────────────────────────────
DATA_MODE="public"
DATA_FILES=$(detect_data_files)
FILE_COUNT=0
[[ -n "$DATA_FILES" ]] && FILE_COUNT=$(echo "$DATA_FILES" | wc -l)

echo ""
if [[ "$FILE_COUNT" -gt 0 ]]; then
    echo -e "${DIM}📂 Found $FILE_COUNT data file(s) in data/${RESET}"
else
    echo -e "${DIM}📂 No data files in data/ yet${RESET}"
fi
echo ""
echo -e "${BOLD}Where should the data come from?${RESET}"
DATA_MODES=("Public databases (TCGA, ClinVar, ChEMBL)" "My data (files in data/)")
select dm in "${DATA_MODES[@]}"; do
    case "$REPLY" in
        1) DATA_MODE="public"; break ;;
        2) DATA_MODE="mydata"; break ;;
        *) echo "Invalid choice." ;;
    esac
done

# ── Follow-up questions ──────────────────────────────────────────────
if [[ -n "${SELECTED_LABEL:-}" ]]; then
    collect_details "$SELECTED_LABEL"
fi

# ── Agent count ──────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}How many agents?${RESET}"
AGENT_OPTS=("1 agent — Simple" "2 agents — Moderate" "3 agents — Full parallelism")
select ac in "${AGENT_OPTS[@]}"; do
    case "$REPLY" in
        1|2|3) AGENT_NUM="$REPLY"; break ;;
        *) echo "Invalid choice." ;;
    esac
done

# ── Vast.ai (compute-heavy tasks) ────────────────────────────────────
USE_VAST="no"
case "${SELECTED_LABEL:-}" in
    "Train Drug Predictor"|"Screen Drug Candidates"|"Predict Protein Shape"|"Predict Target Shape")
        echo ""
        read -rp "Use cloud GPU (Vast.ai)? [y/N] " vast_confirm
        case "$vast_confirm" in
            [yY]*) USE_VAST="yes" ;;
        esac
        ;;
esac

# ── Append options ───────────────────────────────────────────────────
[[ "$DATA_MODE" == "public" ]] && TASK="$TASK Use public databases (TCGA/ClinVar/ChEMBL) for data sourcing."
[[ "${AGENT_NUM:-1}" -gt 1 ]] 2>/dev/null && TASK="$TASK Deploy $AGENT_NUM parallel agents."
[[ "$USE_VAST" == "yes" ]] && TASK="$TASK Use Vast.ai cloud GPU for compute."

echo ""
echo -e "${GREEN}Task:${RESET} $TASK"
[[ "$DATA_MODE" == "public" ]] && echo -e "${DIM}📡 Data: Public databases${RESET}" || echo -e "${DIM}📁 Data: My files${RESET}"
echo -e "${DIM}🤖 Agents: ${AGENT_NUM:-1}${RESET}"
[[ "$USE_VAST" == "yes" ]] && echo -e "${DIM}☁️  Compute: Vast.ai${RESET}" || echo -e "${DIM}🖥️  Compute: Local GPU${RESET}"
echo ""
# ── Run mode ─────────────────────────────────────────────────────────
if ! $LOOP_MODE; then
    echo ""
    echo -e "${BOLD}How should this run?${RESET}"
    RUN_OPTS=("Run once" "Run continuously (keep re-running)")
    select rm in "${RUN_OPTS[@]}"; do
        case "$REPLY" in
            1) break ;;
            2) LOOP_MODE=true; break ;;
            *) echo "Invalid choice." ;;
        esac
    done
fi

echo ""
read -rp "Run this task? [Y/n] " confirm
case "$confirm" in
    [nN]*) echo "Cancelled."; read -r; exit 0 ;;
esac

[[ "$USE_VAST" == "yes" ]] && export LABCLAW_COMPUTE=vast_ai || export LABCLAW_COMPUTE=local

RUN_COUNT=0
while true; do
    RUN_COUNT=$((RUN_COUNT + 1))
    echo ""
    if $LOOP_MODE; then
        echo -e "${GREEN}▶ Run #$RUN_COUNT — Launching research pipeline...${RESET}"
    else
        echo -e "${GREEN}▶ Launching research pipeline...${RESET}"
    fi
    echo ""

    nat run --config_file "$CONFIG" --input "$TASK" 2>&1 | tee -a "$LOG"

    echo ""
    echo -e "${GREEN}✅ Run #$RUN_COUNT complete.${RESET}"

    if ! $LOOP_MODE; then
        echo ""
        echo -e "${DIM}Press Enter to close${RESET}"
        read -r
        break
    fi

    # Continuous mode: countdown with abort
    echo ""
    echo -e "${YELLOW}🔁 Continuous mode — next run in 10 seconds${RESET}"
    echo -e "${DIM}Press Ctrl+C to stop, or wait to continue...${RESET}"
    sleep 10 || {
        echo ""
        echo -e "${GREEN}⏹ Stopped after $RUN_COUNT run(s).${RESET}"
        echo ""
        echo -e "${DIM}Press Enter to close${RESET}"
        read -r
        break
    }
done
