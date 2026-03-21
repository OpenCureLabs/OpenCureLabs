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
    local prompt="$1" placeholder="$2" result
    if $HAS_GUM; then
        result=$(gum file --all --height 10 2>/dev/null) || true
        if [[ -z "$result" ]]; then
            result=$(ask_input "$prompt" "$placeholder")
        fi
    else
        read -rp "$prompt " result
    fi
    echo "$result"
}

# Appends follow-up details to TASK based on SELECTED_LABEL
collect_details() {
    local label="$1"
    local details=""

    echo ""
    gum style --foreground 39 --italic "A few quick questions so the agent knows what to analyze:" 2>/dev/null \
        || echo -e "${CYAN}A few quick questions so the agent knows what to analyze:${RESET}"
    echo ""

    case "$label" in
        "Find Tumor Mutations")
            local tumor normal
            tumor=$(ask_input "Tumor sample file:" "e.g. data/tumor.bam or data/tumor.vcf")
            normal=$(ask_input "Normal (healthy) sample file:" "e.g. data/normal.bam")
            [[ -n "$tumor" ]]  && details+=" Tumor sample: $tumor."
            [[ -n "$normal" ]] && details+=" Normal sample: $normal."
            ;;
        "Predict Neoantigens")
            local vcf hla
            vcf=$(ask_input "Somatic variants file:" "e.g. data/somatic.vcf")
            hla=$(ask_input "HLA type (if known, or leave blank):" "e.g. HLA-A*02:01")
            [[ -n "$vcf" ]] && details+=" Variants file: $vcf."
            [[ -n "$hla" ]] && details+=" HLA type: $hla."
            ;;
        "Map Immune Landscape")
            local expr
            expr=$(ask_input "Gene expression data file:" "e.g. data/expression.tsv")
            [[ -n "$expr" ]] && details+=" Expression data: $expr."
            ;;
        "Check Data Quality")
            local reads
            reads=$(ask_input "Sequencing data file:" "e.g. data/reads.fastq.gz")
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
            lib=$(ask_input "Compound library (or leave blank for default):" "e.g. data/compounds.sdf")
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
            variant=$(ask_input "Variant (VCF file, rsID, or HGVS notation):" "e.g. data/variants.vcf, rs121913529, BRAF V600E")
            [[ -n "$variant" ]] && details+=" Variant: $variant."
            ;;
        "Find New Mutations")
            local child parents
            child=$(ask_input "Child's sequencing file:" "e.g. data/child.vcf")
            parents=$(ask_input "Parents' sequencing files:" "e.g. data/mother.vcf, data/father.vcf")
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

        # ── Follow-up questions ──────────────────────────────────────────
        collect_details "$SELECTED_LABEL"
    fi

    # ── Confirmation ─────────────────────────────────────────────────────
    echo ""
    gum style \
        --border rounded \
        --border-foreground 46 \
        --padding "0 2" \
        --margin "0 0" \
        --foreground 255 \
        "📋 Task: $TASK"

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

    # ── Follow-up questions ──────────────────────────────────────────────
    collect_details "$SELECTED_LABEL"
fi

echo ""
echo -e "${GREEN}Task:${RESET} $TASK"
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
