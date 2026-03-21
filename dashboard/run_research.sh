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

CANCER_TASKS=(
    "Somatic Mutation Calling|Identify somatic mutations from tumor/normal paired sequencing data. Run alignment, variant calling with Mutect2, and annotation."
    "Neoantigen Prediction|Predict neoantigens from somatic variants and HLA typing. Run the full neoantigen pipeline including HLA typing with OptiType."
    "Tumor Microenvironment|Model the tumor-immune microenvironment from expression data using CIBERSORTx deconvolution and immune cell quantification."
    "Sequencing QC (Cancer)|Run sequencing quality control on cancer genomic data. Check read quality, coverage, and contamination."
    "Structure Prediction (Cancer)|Predict protein structure for a cancer-related target using AlphaFold."
)

DRUG_TASKS=(
    "QSAR Model Training|Train a QSAR model on ChEMBL bioactivity data. Compute molecular descriptors with RDKit and train predictive models."
    "Virtual Docking Screen|Run virtual screening via molecular docking. Prepare receptor structure, generate ligand conformers, dock with Vina/Gnina, and rank hits."
    "Compound Optimization|Optimize a lead compound via iterative docking and QSAR analysis. Predict activity and validate binding poses."
    "Structure Prediction (Drug)|Predict protein structure for a drug target using AlphaFold to enable docking studies."
)

RARE_TASKS=(
    "Variant Pathogenicity|Analyze variants for pathogenicity and gene-disease associations. Cross-reference ClinVar and OMIM, rank candidate genes."
    "De Novo Variant Analysis|Identify and score de novo variants in trios. Run trio variant calling, inheritance filtering, and pathogenicity scoring."
    "Sequencing QC (Rare)|Run sequencing quality control on rare disease genomic data. Check read quality, coverage, and contamination."
)

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
        --header "Select research domain:" \
        --header.foreground 39 \
        --cursor.foreground 46 \
        --item.foreground 255 \
        --selected.foreground 46 \
        --selected.bold \
        "🔬 Cancer Immunology" \
        "💊 Drug Response" \
        "🧬 Rare Disease" \
        "⌨️  Custom Task (advanced)" \
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
        # Build labels array
        LABELS=()
        for item in "${ITEMS[@]}"; do
            LABELS+=("${item%%|*}")
        done

        SELECTED=$(gum choose \
            --header "Select task:" \
            --header.foreground 39 \
            --cursor.foreground 46 \
            --item.foreground 255 \
            --selected.foreground 46 \
            --selected.bold \
            "${LABELS[@]}" \
        ) || { echo "Cancelled."; read -r; exit 0; }

        # Find the full description for the selected label
        for item in "${ITEMS[@]}"; do
            label="${item%%|*}"
            if [[ "$label" == "$SELECTED" ]]; then
                TASK="${item#*|}"
                break
            fi
        done
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
echo -e "${BOLD}Select research domain:${RESET}"
echo ""

DOMAINS=("Cancer Immunology" "Drug Response" "Rare Disease" "Custom Task")
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

    LABELS=()
    for item in "${ITEMS[@]}"; do
        LABELS+=("${item%%|*}")
    done

    select label in "${LABELS[@]}"; do
        if [[ -n "$label" ]]; then
            for item in "${ITEMS[@]}"; do
                if [[ "${item%%|*}" == "$label" ]]; then
                    TASK="${item#*|}"
                    break 2
                fi
            done
        fi
        echo "Invalid choice. Try again."
    done
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
