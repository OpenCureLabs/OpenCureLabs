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
#
#  Triggered by Alt+S in the Zellij dashboard.
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail

PROJECT_DIR="/root/opencurelabs"
CONFIG="coordinator/labclaw_workflow.yaml"
LOG="logs/agent.log"

cd "$PROJECT_DIR"
source .venv/bin/activate 2>/dev/null || true

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
while [[ $# -gt 0 ]]; do
    case "$1" in
        --task) TASK="$2"; shift 2 ;;
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

    echo ""
    gum confirm "Launch this research task?" --affirmative "Run" --negative "Cancel" \
        || { echo "Cancelled."; read -r; exit 0; }

    # ── Launch ───────────────────────────────────────────────────────────
    echo ""
    gum style --foreground 46 --bold "▶ Launching research pipeline..."
    echo ""

    nat run --config_file "$CONFIG" --input "$TASK" 2>&1 | tee -a "$LOG"

    echo ""
    gum style --foreground 46 "✅ Pipeline complete."
    echo ""
    echo -e "${DIM}Press Enter to close${RESET}"
    read -r
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

DOMAINS=("Cancer — Find mutations, predict immune targets" "Drug Discovery — Screen molecules, predict effectiveness" "Rare Disease — Analyze genetic variants for diagnosis" "Custom Task — Type your own question")
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
read -rp "Run this task? [Y/n] " confirm
case "$confirm" in
    [nN]*) echo "Cancelled."; read -r; exit 0 ;;
esac

echo ""
echo -e "${GREEN}▶ Launching research pipeline...${RESET}"
echo ""

nat run --config_file "$CONFIG" --input "$TASK" 2>&1 | tee -a "$LOG"

echo ""
echo -e "${GREEN}✅ Pipeline complete.${RESET}"
echo ""
echo -e "${DIM}Press Enter to close${RESET}"
read -r
