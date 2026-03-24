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

# ── Prevent OSC 11 terminal color query artifacts in Zellij ───────────────────
# gum and other TUI tools query the terminal background color via OSC 11.
# Zellij doesn't always intercept the response, leaking ^[]11;rgb:... into output.
# Setting COLORFGBG tells tools "white on black" without needing to query.
export COLORFGBG="15;0"

# ── Error trap: catch crashes in Zellij floating panes ────────────────────────
# Without this, set -e + close_on_exit causes "flash and close" with no output.
_on_error() {
    local exit_code=$?
    echo ""
    echo -e "\033[1;91m── Script error on line $1 (exit code $exit_code) ──\033[0m"
    echo -e "\033[2mPress Enter to close\033[0m"
    read -r
}
trap '_on_error $LINENO' ERR

# ── Teardown handler: destroy Vast.ai instances on interrupt / exit ───────────
_GENESIS_STOP=0
_teardown_vast() {
    _GENESIS_STOP=1
    echo ""
    echo -e "\033[1;93m── Tearing down Vast.ai instances before exit... ──\033[0m"
    # Kill any running nat run children
    pkill -TERM -f "nat run" 2>/dev/null || true
    sleep 1
    pkill -KILL -f "nat run" 2>/dev/null || true
    python3 -c "
from agentiq_labclaw.compute.vast_dispatcher import teardown_all_instances
teardown_all_instances()
" 2>&1 | sed 's/^/  /' || true
}
trap '_teardown_vast; exit 0' INT TERM

export PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CONFIG="coordinator/labclaw_workflow.yaml"
LOG="logs/agent.log"

cd "$PROJECT_DIR" || { echo "Cannot cd to $PROJECT_DIR"; read -r; exit 1; }
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

# ── Parameterize task descriptions ────────────────────────────────────────────
# Converts free-text task descriptions into parameterized instructions with
# concrete gene/protein/compound inputs from the curated task generator.
# Without this, the LLM coordinator asks for clarification instead of acting.
parameterize_task() {
    local desc="$1"
    local species="${LABCLAW_SPECIES:-human}"
    local dm_flag=""
    [[ -n "${DATA_MODE:-}" ]] && dm_flag="--data-mode $DATA_MODE"
    python3 "$PROJECT_DIR/scripts/parameterize_task.py" "$desc" --species "$species" $dm_flag 2>/dev/null \
        || echo "$desc"
}

# In public-database mode, skip tasks that require local data files
# (neoantigen and QC tasks need VCF/FASTQ that won't exist locally).
_skip_local_task() {
    if [[ "${DATA_MODE:-public}" == "public" ]]; then
        local desc_lower="${1,,}"
        case "$desc_lower" in
            *neoantigen*|*"quality control"*|*"data quality"*|*"check data quality"*|*"check "*" data quality"*|*"sequencing qc"*) return 0 ;;
        esac
    fi
    return 1
}

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

CANINE_TASKS=(
    "Find Canine Tumor Mutations ~ Analyse dog tumor vs healthy DNA for somatic mutations|Identify somatic mutations from canine tumor/normal paired sequencing. Use CanFam3.1 reference, Mutect2 variant calling, and Ensembl VEP annotation. species=dog."
    "Predict Canine Neoantigens ~ Find tumor markers the dog's immune system can target|Predict neoantigens from canine somatic variants and DLA typing. Run full canine neoantigen pipeline using DLA-88 alleles and NetMHCpan binding prediction. species=dog."
    "Assess Canine Variant Danger ~ Check if a canine genetic variant causes disease|Analyze canine variants for pathogenicity using OMIA (Online Mendelian Inheritance in Animals) and Ensembl VEP. species=dog."
    "Check Canine Data Quality ~ Verify canine sequencing data before analysis|Run sequencing QC on canine genomic data. Use CanFam3.1 reference for coverage and contamination metrics. species=dog."
)

FELINE_TASKS=(
    "Find Feline Tumor Mutations ~ Analyse cat tumor vs healthy DNA for somatic mutations|Identify somatic mutations from feline tumor/normal paired sequencing. Use felCat9 reference, Mutect2 variant calling, and Ensembl VEP annotation. species=cat."
    "Predict Feline Neoantigens ~ Find tumor markers the cat's immune system can target|Predict neoantigens from feline somatic variants and FLA typing. Run full feline neoantigen pipeline using FLA alleles and NetMHCpan binding prediction. species=cat."
    "Assess Feline Variant Danger ~ Check if a feline genetic variant causes disease|Analyze feline variants for pathogenicity using OMIA and Ensembl VEP with felCat9 reference. species=cat."
    "Check Feline Data Quality ~ Verify feline sequencing data before analysis|Run sequencing QC on feline genomic data. Use felCat9 reference for coverage and contamination metrics. species=cat."
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

# Detect data files in data/ directory
detect_data_files() {
    find "$PROJECT_DIR/data" -type f \
        \( -name "*.vcf" -o -name "*.bam" -o -name "*.fastq*" \
           -o -name "*.csv" -o -name "*.tsv" -o -name "*.sdf" \
           -o -name "*.pdb" -o -name "*.fasta" -o -name "*.fa" \) \
        2>/dev/null || true
}

# Classify the most relevant file in data/ and return: "path|skill|label"
classify_data_files() {
    local vcf fastq bam fasta pdb sdf
    vcf=$(find "$PROJECT_DIR/data" -type f -name "*.vcf" 2>/dev/null | head -1)
    fastq=$(find "$PROJECT_DIR/data" -type f \( -name "*.fastq" -o -name "*.fastq.gz" -o -name "*.fq.gz" \) 2>/dev/null | head -1)
    bam=$(find "$PROJECT_DIR/data" -type f -name "*.bam" 2>/dev/null | head -1)
    fasta=$(find "$PROJECT_DIR/data" -type f \( -name "*.fasta" -o -name "*.fa" \) 2>/dev/null | head -1)
    pdb=$(find "$PROJECT_DIR/data" -type f -name "*.pdb" 2>/dev/null | head -1)
    sdf=$(find "$PROJECT_DIR/data" -type f -name "*.sdf" 2>/dev/null | head -1)

    if [[ -n "$vcf" ]];   then echo "$vcf|variant_pathogenicity|Assess Variant Danger"
    elif [[ -n "$fastq" ]]; then echo "$fastq|sequencing_qc+neoantigen|Check Data Quality → Predict Neoantigens"
    elif [[ -n "$bam" ]];   then echo "$bam|sequencing_qc+neoantigen|Check Data Quality → Predict Neoantigens"
    elif [[ -n "$fasta" ]]; then echo "$fasta|structure_prediction|Predict Protein Shape"
    elif [[ -n "$pdb" ]];   then echo "$pdb|molecular_docking|Screen Drug Candidates"
    elif [[ -n "$sdf" ]];   then echo "$sdf|qsar|Train Drug Predictor"
    fi
}

# Offer to contribute anonymized findings to the OpenCure Labs public dataset.
# Called after a successful solo mode run. Reads reports/last_result.json.
offer_r2_contribution() {
    local last_result="$PROJECT_DIR/reports/last_result.json"
    [[ -f "$last_result" ]] || return 0

    echo ""
    if $HAS_GUM; then
        gum style --foreground 39 --bold "🌐 Contribute to OpenCure Labs?" 2>/dev/null || true
        echo ""
        gum style --foreground 242 "Results saved locally in reports/.  Optionally share anonymized" 2>/dev/null || true
        gum style --foreground 242 "scientific findings with the global dataset — no personal data included." 2>/dev/null || true
        echo ""
        if gum confirm "Contribute anonymized findings to pub.opencurelabs.ai?" \
            --affirmative "Yes, contribute" --negative "No, keep private" \
            --default=false; then
            if gum spin --spinner dot --title "Publishing to global dataset..." -- \
                python3 -c "
import sys, json, os, pathlib
sys.path.insert(0, os.environ['PROJECT_DIR'] + '/packages/agentiq_labclaw')
os.environ['OPENCURELABS_MODE'] = 'contribute'
from agentiq_labclaw.publishers.r2_publisher import R2Publisher
f = pathlib.Path(os.environ['PROJECT_DIR']) / 'reports' / 'last_result.json'
data = json.loads(f.read_text())
r = R2Publisher().publish_result(data['skill_name'], data['result'], novel=data['result'].get('novel', False), status='published')
if not r: sys.exit(1)
"
            then
                gum style --foreground 46 "✅ Contributed! View at https://opencurelabs.ai" 2>/dev/null || true
            else
                gum style --foreground 196 "Could not reach ingest server — results are safe locally." 2>/dev/null || true
            fi
        fi
    else
        echo -e "${CYAN}── Contribute to OpenCure Labs? ──${RESET}"
        echo "Results saved locally in reports/."
        echo "You can optionally share anonymized scientific findings (no personal data)."
        echo ""
        read -rp "Contribute findings to opencurelabs.ai? [y/N] " _contrib
        case "$_contrib" in
            [yY]*)
                echo "Publishing..."
                if python3 -c "
import sys, json, os, pathlib
sys.path.insert(0, os.environ['PROJECT_DIR'] + '/packages/agentiq_labclaw')
os.environ['OPENCURELABS_MODE'] = 'contribute'
from agentiq_labclaw.publishers.r2_publisher import R2Publisher
f = pathlib.Path(os.environ['PROJECT_DIR']) / 'reports' / 'last_result.json'
data = json.loads(f.read_text())
r = R2Publisher().publish_result(data['skill_name'], data['result'], novel=data['result'].get('novel', False), status='published')
if not r: sys.exit(1)
"; then
                    echo -e "${GREEN}✅ Contributed! View at https://opencurelabs.ai${RESET}"
                else
                    echo -e "${RED}Could not reach ingest server — results are safe locally.${RESET}"
                fi
                ;;
        esac
    fi
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
        "Find Tumor Mutations"|"Map Immune Landscape"|"Check Data Quality"|"Find New Mutations"|\
        "Find Canine Tumor Mutations"|"Check Canine Data Quality"|\
        "Find Feline Tumor Mutations"|"Check Feline Data Quality")
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
        # ── Canine veterinary tasks ──────────────────────────────────
        "Find Canine Tumor Mutations")
            local tumor normal
            tumor=$(ask_data_file "Canine tumor sample file:" "e.g. data/dog/tumor.vcf")
            normal=$(ask_data_file "Canine normal sample file:" "e.g. data/dog/normal.bam")
            [[ -n "$tumor" ]]  && details+=" Tumor sample: $tumor."
            [[ -n "$normal" ]] && details+=" Normal sample: $normal."
            ;;
        "Predict Canine Neoantigens")
            local vcf dla
            vcf=$(ask_data_file "Canine somatic variants file:" "e.g. data/dog/somatic.vcf")
            dla=$(ask_input "DLA type (if known, or leave blank):" "e.g. DLA-88*001:01")
            [[ -n "$vcf" ]] && details+=" Variants file: $vcf."
            [[ -n "$dla" ]] && details+=" DLA type: $dla."
            ;;
        "Assess Canine Variant Danger")
            local variant
            if [[ "${DATA_MODE:-public}" == "mydata" ]]; then
                variant=$(ask_file "Canine variant file or ID:" "e.g. data/dog/variants.vcf")
            else
                variant=$(ask_input "Canine variant (gene or OMIA ID):" "e.g. BRAF V595E, MDR1")
            fi
            [[ -n "$variant" ]] && details+=" Variant: $variant."
            ;;
        "Check Canine Data Quality")
            local reads
            reads=$(ask_data_file "Canine sequencing data file:" "e.g. data/dog/reads.fastq.gz")
            [[ -n "$reads" ]] && details+=" Sequencing data: $reads."
            ;;
        # ── Feline veterinary tasks ──────────────────────────────────
        "Find Feline Tumor Mutations")
            local tumor normal
            tumor=$(ask_data_file "Feline tumor sample file:" "e.g. data/cat/tumor.vcf")
            normal=$(ask_data_file "Feline normal sample file:" "e.g. data/cat/normal.bam")
            [[ -n "$tumor" ]]  && details+=" Tumor sample: $tumor."
            [[ -n "$normal" ]] && details+=" Normal sample: $normal."
            ;;
        "Predict Feline Neoantigens")
            local vcf fla
            vcf=$(ask_data_file "Feline somatic variants file:" "e.g. data/cat/somatic.vcf")
            fla=$(ask_input "FLA type (if known, or leave blank):" "e.g. FLA-K*00101")
            [[ -n "$vcf" ]] && details+=" Variants file: $vcf."
            [[ -n "$fla" ]] && details+=" FLA type: $fla."
            ;;
        "Assess Feline Variant Danger")
            local variant
            if [[ "${DATA_MODE:-public}" == "mydata" ]]; then
                variant=$(ask_file "Feline variant file or ID:" "e.g. data/cat/variants.vcf")
            else
                variant=$(ask_input "Feline variant (gene or OMIA ID):" "e.g. PKD1, HCM")
            fi
            [[ -n "$variant" ]] && details+=" Variant: $variant."
            ;;
        "Check Feline Data Quality")
            local reads
            reads=$(ask_data_file "Feline sequencing data file:" "e.g. data/cat/reads.fastq.gz")
            [[ -n "$reads" ]] && details+=" Sequencing data: $reads."
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
    TASK=$(parameterize_task "$TASK")
    echo -e "${CYAN}── Running Task ──${RESET}"
    echo -e "${DIM}$TASK${RESET}"
    echo
    nat run --config_file "$CONFIG" --input "$TASK" 2>&1 | tee -a "$LOG"
    echo
    echo -e "${DIM}Press Enter to close${RESET}"
    read -r
    exit 0
fi

#  GUM MODE — Beautiful interactive menu with ⬅ Back navigation
# ══════════════════════════════════════════════════════════════════════════════
if $HAS_GUM; then

    # ── Step-based navigation (⬅ Back support) ────────────────────────
    # Steps: 1=Domain  2=Species(vet)  3=Task  4=Data  5=Agents  6=RunMode  7=Launch
    _STEP=1
    _BACK_FROM_3=1   # where step 3 goes back to (1 or 2)
    TASK=""
    BASE_TASK=""
    SELECTED_LABEL=""

    while true; do

    # Clear screen on each step to prevent stacking
    clear

    case $_STEP in

    # ══════════════════════════════════════════════════════════════════════
    #  STEP 1 — Domain selection
    # ══════════════════════════════════════════════════════════════════════
    1)
    gum style \
        --border double \
        --border-foreground 39 \
        --padding "0 2" \
        --margin "0 0" \
        --bold \
        "🧬  OpenCure Labs — Research Launcher" 2>/dev/null || true

    echo ""

    DOMAIN=$(gum choose \
        --header "What do you want to research?" \
        --header.foreground 39 \
        --cursor.foreground 46 \
        --item.foreground 255 \
        --selected.foreground 46 \
        --selected.bold \
        "🔬 Cancer — Find mutations, predict immune targets" \
        "🧬 Rare Disease — Analyze genetic variants for diagnosis" \
        "💊 Drug Discovery — Screen molecules, predict effectiveness" \
        "🐾 Veterinary — Cancer & variants for dogs and cats" \
        "⌨️  Custom Task — Type your own research question" \
        "🚀 Genesis Mode — Run EVERY task across ALL domains (20 runs, full send)" \
    ) || { echo "Cancelled."; read -r; exit 0; }

    echo ""

    # Reset state for fresh selection
    LABCLAW_SPECIES="human"
    TASK="" SELECTED_LABEL="" BASE_TASK=""

    case "$DOMAIN" in
        *"Cancer"*)
            ITEMS=("${CANCER_TASKS[@]}"); _BACK_FROM_3=1; _STEP=3 ;;
        *"Veterinary"*)
            _STEP=2 ;;
        *"Drug"*)
            ITEMS=("${DRUG_TASKS[@]}"); _BACK_FROM_3=1; _STEP=3 ;;
        *"Rare"*)
            ITEMS=("${RARE_TASKS[@]}"); _BACK_FROM_3=1; _STEP=3 ;;
        *"Custom"*)
            _BACK_FROM_3=1; _STEP=3 ;;
        *"Genesis"*)
            # ── Genesis Mode ─────────────────────────────────────────────
            # Run EVERY task across ALL domains: 20 runs, full agents, Vast.ai
            ALL_TASKS=()
            ALL_LABELS=()
            ALL_DOMAINS=()

            for t in "${CANCER_TASKS[@]}"; do
                _skip_local_task "${t#*|}" && continue
                ALL_TASKS+=("${t#*|}")
                ALL_LABELS+=("${t%%|*}")
                ALL_DOMAINS+=("Cancer")
            done
            for t in "${DRUG_TASKS[@]}"; do
                _skip_local_task "${t#*|}" && continue
                ALL_TASKS+=("${t#*|}")
                ALL_LABELS+=("${t%%|*}")
                ALL_DOMAINS+=("Drug Discovery")
            done
            for t in "${RARE_TASKS[@]}"; do
                _skip_local_task "${t#*|}" && continue
                ALL_TASKS+=("${t#*|}")
                ALL_LABELS+=("${t%%|*}")
                ALL_DOMAINS+=("Rare Disease")
            done
            for t in "${CANINE_TASKS[@]}"; do
                _skip_local_task "${t#*|}" && continue
                ALL_TASKS+=("${t#*|}")
                ALL_LABELS+=("${t%%|*}")
                ALL_DOMAINS+=("Veterinary 🐕")
            done
            for t in "${FELINE_TASKS[@]}"; do
                _skip_local_task "${t#*|}" && continue
                ALL_TASKS+=("${t#*|}")
                ALL_LABELS+=("${t%%|*}")
                ALL_DOMAINS+=("Veterinary 🐈")
            done

            TOTAL=${#ALL_TASKS[@]}

            # ── Data source picker ────────────────────────────────
            DATA_FILES=$(detect_data_files)
            FILE_COUNT=0
            [[ -n "$DATA_FILES" ]] && FILE_COUNT=$(echo "$DATA_FILES" | wc -l)

            echo ""
            if [[ "$FILE_COUNT" -gt 0 ]]; then
                gum style --foreground 242 --italic \
                    "📂 Found $FILE_COUNT data file(s) in data/" 2>/dev/null \
                    || echo -e "${DIM}📂 Found $FILE_COUNT data file(s) in data/${RESET}"
            fi
            echo ""

            DATA_MODE_CHOICE=$(gum choose \
                --header "Where should the data come from?" \
                --header.foreground 39 \
                --cursor.foreground 46 \
                --item.foreground 255 \
                --selected.foreground 46 \
                --selected.bold \
                "⬅ Back" \
                "🌐 Public databases — Search TCGA, ClinVar, ChEMBL automatically" \
                "📁 My data — Use files I've uploaded to data/" \
            ) || { echo "Cancelled."; read -r; exit 0; }

            case "$DATA_MODE_CHOICE" in
                *"Back"*) _STEP=1; continue ;;
                *"Public"*)  DATA_MODE="public" ;;
                *"My data"*) DATA_MODE="mydata" ;;
            esac

            if [[ "$DATA_MODE" == "mydata" ]]; then
                GENESIS_DATA_SUFFIX="Use uploaded files in data/ for analysis. Focus on the patient's own data."
                DATA_SOURCE_LABEL="📁 My data — files in data/"

                # Show what was found and where to put files
                echo ""
                _data_summary=""
                _file_list=""
                if [[ "$FILE_COUNT" -gt 0 ]]; then
                    _data_summary="  ✅ Found $FILE_COUNT file(s) in data/"
                    _file_list=$(echo "$DATA_FILES" | head -8 | while read -r f; do
                        echo "     $(basename "$f")"
                    done)
                    if [[ $(echo "$DATA_FILES" | wc -l) -gt 8 ]]; then
                        _file_list="$_file_list
     … and $(($(echo "$DATA_FILES" | wc -l) - 8)) more"
                    fi
                else
                    _data_summary="  ⚠️  No data files found yet"
                fi

                printf '%s\n' \
                    "" \
                    "  📁  M Y   D A T A" \
                    "" \
                    "$_data_summary" \
                    "$_file_list" \
                    "" \
                    "  Put your files in:  data/" \
                    "" \
                    "  Supported formats:" \
                    "    Genomics    .vcf .bam .fastq .fastq.gz" \
                    "    Sequences   .fasta .fa" \
                    "    Structures  .pdb" \
                    "    Compounds   .sdf" \
                    "    Tables      .csv .tsv" \
                    "" \
                | (gum style \
                    --border rounded \
                    --border-foreground 39 \
                    --foreground 252 \
                    --padding "0 1" 2>/dev/null || cat)
            else
                GENESIS_DATA_SUFFIX="Use public databases (TCGA/ClinVar/ChEMBL) for data sourcing."
                DATA_SOURCE_LABEL="🌐 Public databases — TCGA, ClinVar, ChEMBL"
            fi

            echo ""
            printf '%s\n' \
                "" \
                "  🚀  G E N E S I S   M O D E" \
                "" \
                "  $TOTAL tasks across 5 domains" \
                "  $DATA_SOURCE_LABEL" \
                "" \
                "  ┌─ Cancer (5 tasks) ──────────────────────┐" \
                "  │  Tumor Mutations · Neoantigens · Immune  │" \
                "  │  Landscape · Data QC · Protein Shape     │" \
                "  ├─ Drug Discovery (4 tasks) ───────────────┤" \
                "  │  Train Predictor · Screen Candidates      │" \
                "  │  Optimize Lead · Target Shape             │" \
                "  ├─ Rare Disease (3 tasks) ──────────────────┤" \
                "  │  Variant Danger · New Mutations · Data QC │" \
                "  ├─ Veterinary 🐕 Canine (4 tasks) ──────────┤" \
                "  │  Tumor Mutations · Neoantigens · Variants │" \
                "  │  · Data QC                                │" \
                "  ├─ Veterinary 🐈 Feline (4 tasks) ──────────┤" \
                "  │  Tumor Mutations · Neoantigens · Variants │" \
                "  │  · Data QC                                │" \
                "  └───────────────────────────────────────────┘" \
                "" \
            | (gum style \
                --border double \
                --border-foreground 214 \
                --foreground 214 \
                --bold \
                --padding "0 1" \
                --margin "0 0" 2>/dev/null || cat)

            # ── Throughput mode ───────────────────────────────────────
            _EXEC_PICK=1
            while [[ $_EXEC_PICK -eq 1 ]]; do
            _EXEC_PICK=0
            echo ""
            VAST_INSTANCES=$(gum choose \
                --header "Execution mode:" \
                --header.foreground 214 \
                --cursor.foreground 46 \
                --item.foreground 252 \
                --selected.foreground 46 \
                --selected.bold \
                "⬅ Back" \
                "1 — Sequential (safest, lowest cost)" \
                "3 — Fast parallel" \
                "6 — Max throughput" \
                "12 — All at once" \
                "999 — Continuous batch (Vast.ai pool, loops until budget exhausted)" \
            ) || { echo "Cancelled."; read -r; exit 0; }
            if [[ "$VAST_INSTANCES" == *"Back"* ]]; then
                _STEP=1; continue 2
            fi
            PARALLEL="${VAST_INSTANCES%%[[:space:]]*}"
            if [[ $PARALLEL -ge 100 ]]; then
                BATCH_MODE=1
                CONTINUOUS_BATCH=1
                # Prompt for batch parameters before confirmation
                gum style --foreground 242 --italic \
                    "Each task is one research job (e.g. tumor analysis, drug screen)." \
                    "Tasks are queued and distributed across your GPU pool." 2>/dev/null || true
                echo ""
                _TASK_PICK=$(gum choose \
                    --header "How many research tasks per cycle?" \
                    --header.foreground 214 \
                    --cursor.foreground 46 \
                    --item.foreground 252 \
                    --selected.foreground 46 \
                    --selected.bold \
                    "⬅ Back" \
                    "25 tasks" \
                    "50 tasks" \
                    "100 tasks" \
                    "250 tasks" \
                    "500 tasks" \
                    "Custom" \
                ) || { _EXEC_PICK=1; continue; }
                if [[ "$_TASK_PICK" == *"Back"* ]]; then _EXEC_PICK=1; continue; fi
                if [[ "$_TASK_PICK" == "Custom" ]]; then
                    BATCH_COUNT=$(gum input \
                        --header "Enter task count (1-500):" \
                        --placeholder "100" \
                        --value "100" \
                        --header.foreground 214 \
                        --prompt.foreground 46 \
                    ) || { _EXEC_PICK=1; continue; }
                    # Validate: integer between 1-500
                    if ! [[ "$BATCH_COUNT" =~ ^[0-9]+$ ]] || [[ "$BATCH_COUNT" -lt 1 ]]; then
                        BATCH_COUNT=100
                    elif [[ "$BATCH_COUNT" -gt 500 ]]; then
                        BATCH_COUNT=500
                        gum style --foreground 196 "  ⚠️  Capped to 500 tasks (budget protection)"
                    fi
                else
                    BATCH_COUNT="${_TASK_PICK%% *}"
                fi

                _REC_POOL=$((BATCH_COUNT / 10 < 1 ? 1 : BATCH_COUNT / 10 > 20 ? 20 : BATCH_COUNT / 10))
                echo ""
                gum style --foreground 242 --italic \
                    "GPU instances run tasks in parallel — more instances = faster," \
                    "but each costs ~\$0.50/hr. Aim for ~10 tasks per instance." 2>/dev/null || true
                echo ""
                _POOL_PICK=$(gum choose \
                    --header "How many Vast.ai GPU instances?" \
                    --header.foreground 214 \
                    --cursor.foreground 46 \
                    --item.foreground 252 \
                    --selected.foreground 46 \
                    --selected.bold \
                    "⬅ Back" \
                    "Recommended: $_REC_POOL (for $BATCH_COUNT tasks)" \
                    "1 instance" \
                    "2 instances" \
                    "5 instances" \
                    "10 instances" \
                    "20 instances" \
                    "Custom" \
                ) || { _EXEC_PICK=1; continue; }
                if [[ "$_POOL_PICK" == *"Back"* ]]; then _EXEC_PICK=1; continue; fi
                if [[ "$_POOL_PICK" == "Custom" ]]; then
                    POOL_SIZE=$(gum input \
                        --header "Enter instance count (1-20):" \
                        --placeholder "$_REC_POOL" \
                        --value "$_REC_POOL" \
                        --header.foreground 214 \
                        --prompt.foreground 46 \
                    ) || { _EXEC_PICK=1; continue; }
                    # Validate: integer between 1-20
                    if ! [[ "$POOL_SIZE" =~ ^[0-9]+$ ]] || [[ "$POOL_SIZE" -lt 1 ]]; then
                        POOL_SIZE=$_REC_POOL
                    elif [[ "$POOL_SIZE" -gt 20 ]]; then
                        POOL_SIZE=20
                        gum style --foreground 196 "  ⚠️  Capped to 20 instances (budget protection)"
                    fi
                elif [[ "$_POOL_PICK" == Recommended* ]]; then
                    POOL_SIZE=$_REC_POOL
                else
                    POOL_SIZE="${_POOL_PICK%% *}"
                fi

                TOTAL="$BATCH_COUNT"
                if [[ "${CONTINUOUS_BATCH:-0}" -eq 1 ]]; then
                    MODE_LABEL="continuous batch ($POOL_SIZE instances, loops until budget)"
                else
                    MODE_LABEL="batch ($POOL_SIZE instances)"
                fi

                # Show updated batch summary
                echo ""
                EST_COST=$(python3 -c "print(f'\${(int(\"$POOL_SIZE\") * 0.50 * 0.5):.2f}')" 2>/dev/null || echo "?")
                if [[ "${CONTINUOUS_BATCH:-0}" -eq 1 ]]; then
                    printf '%s\n' \
                        "" \
                        "  🔄  C O N T I N U O U S   B A T C H" \
                        "" \
                        "  $BATCH_COUNT tasks/cycle → $POOL_SIZE Vast.ai instances" \
                        "  Loops until budget exhausted or Ctrl+C" \
                        "  Est. cost per cycle: ~\$$EST_COST" \
                        "" \
                    | (gum style \
                        --border double \
                        --border-foreground 214 \
                        --foreground 214 \
                        --bold \
                        --padding "0 1" 2>/dev/null || cat)
                else
                    printf '%s\n' \
                        "" \
                        "  📦  B A T C H   M O D E" \
                        "" \
                        "  $BATCH_COUNT tasks → $POOL_SIZE Vast.ai instances" \
                        "  Estimated cost: ~\$$EST_COST (at \$0.50/hr, ~30min)" \
                        "" \
                    | (gum style \
                        --border rounded \
                        --border-foreground 46 \
                        --foreground 46 \
                        --bold \
                        --padding "0 1" 2>/dev/null || cat)
                fi
            else
                BATCH_MODE=0
                [[ $PARALLEL -eq 1 ]] && MODE_LABEL="sequential" || MODE_LABEL="$PARALLEL parallel"
            fi
            done  # end _EXEC_PICK loop

            # ── Budget picker (Vast.ai batch mode) ─────────────────────
            if [[ "${BATCH_MODE:-0}" -eq 1 ]]; then
                API_BALANCE=$(get_vast_balance)
                VAST_SPENT=$(psql -p 5433 -d opencurelabs -t -A -c \
                    "SELECT COALESCE(SUM(total_cost), 0) FROM vast_spend" 2>/dev/null || echo "0")
                AVAILABLE=$(python3 -c "print(f'{max(0, float(\"$API_BALANCE\") - float(\"$VAST_SPENT\")):.0f}')" 2>/dev/null || echo "$API_BALANCE")

                echo ""
                if python3 -c "exit(0 if float('$AVAILABLE') > 0 else 1)" 2>/dev/null; then
                    gum style --foreground 214 \
                        "  💰 Vast.ai — \$$API_BALANCE balance, \$$VAST_SPENT spent this session" 2>/dev/null \
                        || echo -e "${YELLOW}  💰 Vast.ai — \$$API_BALANCE balance, \$$VAST_SPENT spent this session${RESET}"

                    # Build budget options based on available balance
                    BUDGET_OPTS=()
                    for amt in 5 10 25 50; do
                        if python3 -c "exit(0 if $amt <= float('$AVAILABLE') else 1)" 2>/dev/null; then
                            case $amt in
                                5)  BUDGET_OPTS+=("\$5  — Quick test (a few tasks)") ;;
                                10) BUDGET_OPTS+=("\$10 — Small run") ;;
                                25) BUDGET_OPTS+=("\$25 — Medium run") ;;
                                50) BUDGET_OPTS+=("\$50 — Big run") ;;
                            esac
                        fi
                    done
                    BUDGET_OPTS+=("\$$AVAILABLE — Full send (entire balance)")
                    BUDGET_OPTS+=("Custom amount...")

                    echo ""
                    BUDGET_CHOICE=$(gum choose \
                        --header "How much to spend on this run?" \
                        --header.foreground 214 \
                        --cursor.foreground 46 \
                        --item.foreground 252 \
                        --selected.foreground 46 \
                        --selected.bold \
                        "${BUDGET_OPTS[@]}" \
                    ) || { echo "Cancelled."; read -r; exit 0; }

                    case "$BUDGET_CHOICE" in
                        *"Custom"*)
                            VAST_BUDGET=$(gum input \
                                --header "Enter budget in USD (1-$AVAILABLE):" \
                                --placeholder "$AVAILABLE" \
                                --width 10 2>/dev/null) || VAST_BUDGET="$AVAILABLE"
                            # Validate
                            if ! [[ "$VAST_BUDGET" =~ ^[0-9]+\.?[0-9]*$ ]]; then
                                VAST_BUDGET="$AVAILABLE"
                            elif python3 -c "exit(0 if float('$VAST_BUDGET') > float('$AVAILABLE') else 1)" 2>/dev/null; then
                                VAST_BUDGET="$AVAILABLE"
                                gum style --foreground 196 "  ⚠️  Capped to \$$AVAILABLE (account balance)" 2>/dev/null || true
                            elif python3 -c "exit(0 if float('$VAST_BUDGET') < 1 else 1)" 2>/dev/null; then
                                VAST_BUDGET=1
                            fi
                            ;;
                        *)
                            # Extract dollar amount from choice string
                            VAST_BUDGET=$(echo "$BUDGET_CHOICE" | grep -oP '^\$\K[0-9]+')
                            ;;
                    esac

                    export VAST_AI_BUDGET="$VAST_BUDGET"
                    echo ""
                    gum style --foreground 46 --bold \
                        "  🔒 Budget locked: \$$VAST_BUDGET — continuous until exhausted" 2>/dev/null \
                        || echo -e "${GREEN}  🔒 Budget locked: \$$VAST_BUDGET — continuous until exhausted${RESET}"
                else
                    VAST_BUDGET=0
                    gum style --foreground 196 \
                        "  ⚠️  No Vast.ai balance — will run once locally" 2>/dev/null \
                        || echo -e "${RED}  ⚠️  No Vast.ai balance — will run once locally${RESET}"
                fi
            else
                # Local modes — fetch balance for loop control
                API_BALANCE=$(get_vast_balance)
                VAST_BUDGET="$API_BALANCE"
            fi

            echo ""
            gum confirm "Launch Genesis Mode? ($TOTAL tasks, $MODE_LABEL)" \
                --affirmative "🚀 SEND IT" --negative "Cancel" \
                || { echo "Cancelled."; read -r; exit 0; }

            # ── Genesis Continuous Loop ───────────────────────────────────
            echo ""
            gum style --foreground 214 --bold "🚀 Genesis Mode activated — $TOTAL tasks, $MODE_LABEL" 2>/dev/null || true
            echo ""

            GENESIS_TOTAL_OK=0
            GENESIS_TOTAL_FAILED=0
            GENESIS_START=$(date +%s)
            ROUND=0

            export LABCLAW_COMPUTE=local
            [[ "$DATA_MODE" == "mydata" ]] && export OPENCURELABS_MODE=solo || export OPENCURELABS_MODE=contribute

            # ── BATCH MODE: dispatch to Vast.ai instance pool ─────────────
            if [[ "${BATCH_MODE:-0}" -eq 1 ]]; then
                export LABCLAW_COMPUTE=vast_ai
                echo ""
                gum style --foreground 214 --bold \
                    "  🔄 Continuous batch: $BATCH_COUNT tasks/cycle → $POOL_SIZE instances (until budget exhausted)"
                echo ""

                BATCH_LOG="$PROJECT_DIR/logs/batch-$(date +%Y%m%d-%H%M%S).log"

                BATCH_CMD=(python3 -m agentiq_labclaw.compute.batch_dispatcher
                    --count "$BATCH_COUNT"
                    --pool-size "$POOL_SIZE"
                    --max-cost 0.50
                    --config "$PROJECT_DIR/config/research_tasks.yaml"
                )
                BATCH_CMD+=(--continuous)
                # Pass budget if set
                if [[ -n "${VAST_AI_BUDGET:-}" ]] && [[ "$VAST_AI_BUDGET" != "0" ]]; then
                    BATCH_CMD+=(--budget "$VAST_AI_BUDGET")
                fi

                "${BATCH_CMD[@]}" 2>&1 | tee "$BATCH_LOG"

                export LABCLAW_COMPUTE=local
                echo ""
                gum style --foreground 214 "  📋 Batch log: $BATCH_LOG"
                echo ""
                gum style --foreground 242 "Press Enter to close"
                read -r
                exit 0
            fi

            while true; do
                # Check stop flag (set by SIGINT/SIGTERM trap)
                [[ "$_GENESIS_STOP" -eq 1 ]] && break

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
                        GENESIS_TASK="${ALL_TASKS[$i]} $GENESIS_DATA_SUFFIX Deploy 3 parallel agents. Use Vast.ai cloud GPU for compute."
                        GENESIS_TASK=$(parameterize_task "$GENESIS_TASK")
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
                            GENESIS_TASK="${ALL_TASKS[$i]} $GENESIS_DATA_SUFFIX Deploy 3 parallel agents. Use Vast.ai cloud GPU for compute."
                            GENESIS_TASK=$(parameterize_task "$GENESIS_TASK")
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
                            # Abort batch loop if stop requested
                            [[ "$_GENESIS_STOP" -eq 1 ]] && break
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

            # ── Teardown persistent pool instances ───────────────────────
            gum style --foreground 214 "  🧹 Tearing down Vast.ai pool instances..." 2>/dev/null || true
            python3 -c "
from agentiq_labclaw.compute.vast_dispatcher import teardown_all_instances
teardown_all_instances()
" 2>&1 | sed 's/^/  /' || true

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
            | (gum style \
                --border double \
                --border-foreground "$( [[ $GENESIS_TOTAL_FAILED -eq 0 ]] && echo 46 || echo 196 )" \
                --foreground "$( [[ $GENESIS_TOTAL_FAILED -eq 0 ]] && echo 46 || echo 214 )" \
                --bold \
                --padding "0 2" \
                --margin "0 0" 2>/dev/null || cat)

            echo ""
            echo -e "${DIM}Press Enter to close${RESET}"
            read -r
            exit 0
            ;;
    esac
    ;;

    # ══════════════════════════════════════════════════════════════════════
    #  STEP 2 — Species selection (Veterinary only)
    # ══════════════════════════════════════════════════════════════════════
    2)
    echo ""
    VET_SPECIES=$(gum choose \
        --header "Which animal?" \
        --header.foreground 39 \
        --cursor.foreground 46 \
        --item.foreground 255 \
        --selected.foreground 46 \
        --selected.bold \
        "⬅ Back" \
        "🐾 All Species — Run both canine and feline tasks" \
        "🐕 Dog (Canine) — CanFam3.1, DLA alleles" \
        "🐈 Cat (Feline) — felCat9, FLA alleles" \
    ) || { echo "Cancelled."; read -r; exit 0; }
    if [[ "$VET_SPECIES" == *"Back"* ]]; then
        _STEP=1; continue
    fi
    case "$VET_SPECIES" in
        *"All"*) LABCLAW_SPECIES="all"; ITEMS=("${CANINE_TASKS[@]}" "${FELINE_TASKS[@]}") ;;
        *"Dog"*) LABCLAW_SPECIES="dog"; ITEMS=("${CANINE_TASKS[@]}") ;;
        *"Cat"*) LABCLAW_SPECIES="cat"; ITEMS=("${FELINE_TASKS[@]}") ;;
    esac
    _BACK_FROM_3=2
    _STEP=3
    ;;

    # ══════════════════════════════════════════════════════════════════════
    #  STEP 3 — Task selection (or Custom input)
    # ══════════════════════════════════════════════════════════════════════
    3)
    if [[ "$DOMAIN" == *"Custom"* ]]; then
        # Custom task: free-text input
        TASK=$(gum input \
            --placeholder "Describe your research task... (empty = go back)" \
            --prompt "Task: " \
            --prompt.foreground 46 \
            --width 80 \
            --char-limit 500 \
        ) || { _STEP=1; continue; }

        if [[ -z "$TASK" ]]; then
            _STEP=1; continue
        fi
        SELECTED_LABEL=""
    else
        # Build display labels:  "Label — explanation"
        DISPLAY=()
        for item in "${ITEMS[@]}"; do
            raw="${item%%|*}"           # "Label ~ explanation"
            label="${raw%% ~*}"         # "Label"
            desc="${raw#*~ }"           # "explanation"
            DISPLAY+=("$label — $desc")
        done

        ITEM_COUNT=${#ITEMS[@]}

        SELECTED=$(gum choose \
            --header "Select task:" \
            --header.foreground 39 \
            --cursor.foreground 46 \
            --item.foreground 252 \
            --selected.foreground 46 \
            --selected.bold \
            "⬅ Back" \
            "${DISPLAY[@]}" \
            "🚀 Run All — Execute all $ITEM_COUNT tasks in this domain" \
        ) || { echo "Cancelled."; read -r; exit 0; }

        if [[ "$SELECTED" == *"Back"* ]]; then
            _STEP=$_BACK_FROM_3; continue
        fi

        RUN_ALL=false
        if [[ "$SELECTED" == *"Run All"* ]]; then
            RUN_ALL=true
            # Build combined task list for sequential execution
            RUN_ALL_TASKS=()
            RUN_ALL_LABELS=()
            for item in "${ITEMS[@]}"; do
                RUN_ALL_TASKS+=("${item#*|}")
                raw="${item%%|*}"
                RUN_ALL_LABELS+=("${raw%% ~*}")
            done
            TASK="${RUN_ALL_TASKS[0]}"
            SELECTED_LABEL=""
        else
            # Extract the label part (before " — ") and find matching task
            SELECTED_LABEL="${SELECTED%% — *}"
            TASK=""
            for item in "${ITEMS[@]}"; do
                raw="${item%%|*}"
                label="${raw%% ~*}"
                if [[ "$label" == "$SELECTED_LABEL" ]]; then
                    TASK="${item#*|}"
                    break
                fi
            done
        fi
    fi

    BASE_TASK="$TASK"
    _STEP=4
    ;;

    # ══════════════════════════════════════════════════════════════════════
    #  STEP 4 — Data source selection
    # ══════════════════════════════════════════════════════════════════════
    4)
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
        "⬅ Back" \
        "🌐 Public databases — Search TCGA, ClinVar, ChEMBL automatically" \
        "📁 My data — Use files I've uploaded to data/" \
    ) || { echo "Cancelled."; read -r; exit 0; }

    if [[ "$DATA_MODE_CHOICE" == *"Back"* ]]; then
        _STEP=3; continue
    fi

    case "$DATA_MODE_CHOICE" in
        *"Public"*)  DATA_MODE="public" ;;
        *"My data"*) DATA_MODE="mydata" ;;
    esac

    if [[ "$DATA_MODE" == "mydata" ]]; then
        echo ""
        _data_summary=""
        _file_list=""
        if [[ "$FILE_COUNT" -gt 0 ]]; then
            _data_summary="  ✅ Found $FILE_COUNT file(s) in data/"
            _file_list=$(echo "$DATA_FILES" | head -8 | while read -r f; do
                echo "     $(basename "$f")"
            done)
            if [[ $(echo "$DATA_FILES" | wc -l) -gt 8 ]]; then
                _file_list="$_file_list
     … and $(($(echo "$DATA_FILES" | wc -l) - 8)) more"
            fi
        else
            _data_summary="  ⚠️  No data files found yet"
        fi

        printf '%s\n' \
            "" \
            "  📁  M Y   D A T A" \
            "" \
            "$_data_summary" \
            "$_file_list" \
            "" \
            "  Put your files in:  data/" \
            "" \
            "  Supported formats:" \
            "    Genomics    .vcf .bam .fastq .fastq.gz" \
            "    Sequences   .fasta .fa" \
            "    Structures  .pdb" \
            "    Compounds   .sdf" \
            "    Tables      .csv .tsv" \
            "" \
        | (gum style \
            --border rounded \
            --border-foreground 39 \
            --foreground 252 \
            --padding "0 1" 2>/dev/null || cat)
    fi

    # ── Follow-up questions ──────────────────────────────────────────
    TASK="$BASE_TASK"
    if [[ -n "${SELECTED_LABEL:-}" ]]; then
        collect_details "$SELECTED_LABEL"
    fi

    _STEP=5
    ;;

    # ══════════════════════════════════════════════════════════════════════
    #  STEP 5 — Agent count + Vast.ai burst
    # ══════════════════════════════════════════════════════════════════════
    5)
    echo ""
    AGENT_COUNT=$(gum choose \
        --header "How many agents should work on this?" \
        --header.foreground 39 \
        --cursor.foreground 46 \
        --item.foreground 252 \
        --selected.foreground 46 \
        --selected.bold \
        "⬅ Back" \
        "1 agent  — Simple, sequential analysis" \
        "2 agents — Moderate parallelism" \
        "3 agents — Full parallelism" \
    ) || { echo "Cancelled."; read -r; exit 0; }

    if [[ "$AGENT_COUNT" == *"Back"* ]]; then
        _STEP=4; continue
    fi

    AGENT_NUM="${AGENT_COUNT%%[[:space:]]*}"

    # ── Vast.ai burst (compute-heavy tasks) ──────────────────────────
    USE_VAST="no"
    if [[ "${DATA_MODE:-public}" == "public" ]]; then
        case "${SELECTED_LABEL:-}" in
            "Train Drug Predictor"|"Screen Drug Candidates"|"Predict Protein Shape"|"Predict Target Shape")
                echo ""
                if gum confirm "Use cloud GPU (Vast.ai) for faster results?" \
                    --affirmative "Yes, use cloud" --negative "No, local GPU"; then
                    USE_VAST="yes"
                fi
                ;;
        esac
    fi

    _STEP=6
    ;;

    # ══════════════════════════════════════════════════════════════════════
    #  STEP 6 — Run mode + Confirmation + Launch
    # ══════════════════════════════════════════════════════════════════════
    6)
    # ── Build final task string ──────────────────────────────────────
    FINAL_TASK="$TASK"
    [[ "$DATA_MODE" == "public" ]] && FINAL_TASK="$FINAL_TASK Use public databases (TCGA/ClinVar/ChEMBL) for data sourcing."
    [[ "${AGENT_NUM:-1}" -gt 1 ]] 2>/dev/null && FINAL_TASK="$FINAL_TASK Deploy $AGENT_NUM parallel agents."
    [[ "$USE_VAST" == "yes" ]] && FINAL_TASK="$FINAL_TASK Use Vast.ai cloud GPU for compute."
    TASK="$FINAL_TASK"

    # ── Confirmation summary ─────────────────────────────────────────
    echo ""
    if ${RUN_ALL:-false}; then
        TASK_SUMMARY="🚀 Run All — ${#RUN_ALL_TASKS[@]} tasks in domain"
    else
        TASK_SUMMARY="📋 Task: $TASK"
    fi
    printf '%s\n' \
        "$TASK_SUMMARY" \
        "$([[ "$DATA_MODE" == "public" ]] && echo "📡 Data: Public databases" || echo "📁 Data: My files")" \
        "🤖 Agents: ${AGENT_NUM:-1}" \
        "$([[ "$USE_VAST" == "yes" ]] && echo "☁️  Compute: Vast.ai cloud GPU" || echo "🖥️  Compute: Local GPU")" \
    | (gum style \
        --border rounded \
        --border-foreground 46 \
        --padding "0 2" \
        --margin "0 0" \
        --foreground 255 2>/dev/null || cat)

    # ── Run mode ─────────────────────────────────────────────────────
    if ! $LOOP_MODE; then
        echo ""
        RUN_MODE=$(gum choose \
            --header "How should this run?" \
            --header.foreground 39 \
            --cursor.foreground 46 \
            --item.foreground 252 \
            --selected.foreground 46 \
            --selected.bold \
            "⬅ Back" \
            "▶ Run once — Execute and stop" \
            "🔁 Run continuously — Keep re-running until stopped" \
        ) || { echo "Cancelled."; read -r; exit 0; }

        if [[ "$RUN_MODE" == *"Back"* ]]; then
            _STEP=5; continue
        fi

        case "$RUN_MODE" in
            *"continuously"*) LOOP_MODE=true ;;
        esac
    fi

    # ── Final confirmation ───────────────────────────────────────────
    echo ""
    LAUNCH_CHOICE=$(gum choose \
        --header "Ready to launch?" \
        --header.foreground 46 \
        --cursor.foreground 46 \
        --item.foreground 252 \
        --selected.foreground 46 \
        --selected.bold \
        "▶ Launch — Start the research pipeline" \
        "⬅ Back — Change settings" \
        "✖ Cancel — Exit" \
    ) || { echo "Cancelled."; read -r; exit 0; }

    case "$LAUNCH_CHOICE" in
        *"Back"*) _STEP=5; continue ;;
        *"Cancel"*) echo "Cancelled."; read -r; exit 0 ;;
    esac

    # ── Launch ───────────────────────────────────────────────────────
    [[ "$USE_VAST" == "yes" ]] && export LABCLAW_COMPUTE=vast_ai || export LABCLAW_COMPUTE=local
    # Solo mode: My Data runs are private — only PDF publisher fires locally.
    [[ "$DATA_MODE" == "mydata" ]] && export OPENCURELABS_MODE=solo || export OPENCURELABS_MODE=contribute
    # Species routing — propagated to all LabClaw skills via environment
    export LABCLAW_SPECIES="${LABCLAW_SPECIES:-human}"
    [[ "$LABCLAW_SPECIES" != "human" ]] && TASK="$TASK species=$LABCLAW_SPECIES."

    # ── Run All: sequential multi-task execution ─────────────────────
    if ${RUN_ALL:-false}; then
        TOTAL_ALL=${#RUN_ALL_TASKS[@]}
        ROUND=0

        while true; do
        ROUND=$((ROUND + 1))
        ALL_OK=0
        ALL_FAILED=0

        echo ""
        if $LOOP_MODE; then
            gum style --foreground 46 --bold "🚀 Round $ROUND — Running all $TOTAL_ALL tasks sequentially..." 2>/dev/null || true
        else
            gum style --foreground 46 --bold "🚀 Running all $TOTAL_ALL tasks sequentially..." 2>/dev/null || true
        fi
        echo ""

        for i in $(seq 0 $((TOTAL_ALL - 1))); do
            TASK_NUM=$((i + 1))
            LABEL="${RUN_ALL_LABELS[$i]}"
            CURRENT_TASK="${RUN_ALL_TASKS[$i]}"

            # Skip tasks requiring local data in public-database mode
            if _skip_local_task "$CURRENT_TASK"; then
                gum style --foreground 242 "  ⏭ [R${ROUND} ${TASK_NUM}/$TOTAL_ALL] $LABEL — skipped (needs local data)" 2>/dev/null || true
                continue
            fi

            [[ "$DATA_MODE" == "public" ]] && CURRENT_TASK="$CURRENT_TASK Use public databases (TCGA/ClinVar/ChEMBL) for data sourcing."
            [[ "${AGENT_NUM:-1}" -gt 1 ]] 2>/dev/null && CURRENT_TASK="$CURRENT_TASK Deploy $AGENT_NUM parallel agents."
            [[ "$USE_VAST" == "yes" ]] && CURRENT_TASK="$CURRENT_TASK Use Vast.ai cloud GPU for compute."
            [[ "$LABCLAW_SPECIES" != "human" ]] && CURRENT_TASK="$CURRENT_TASK species=$LABCLAW_SPECIES."
            CURRENT_TASK=$(parameterize_task "$CURRENT_TASK")

            gum style --foreground 214 --bold \
                "  ▶ [R${ROUND} ${TASK_NUM}/$TOTAL_ALL] $LABEL" 2>/dev/null || true

            TASK_LOG="$PROJECT_DIR/logs/runall-$(date +%Y%m%d-%H%M%S)-${TASK_NUM}.log"

            if nat run --config_file "$CONFIG" --input "$CURRENT_TASK" \
                2>&1 | tee -a "$TASK_LOG"; then
                ALL_OK=$((ALL_OK + 1))
                gum style --foreground 46 "  ✅ [R${ROUND} ${TASK_NUM}/$TOTAL_ALL] $LABEL — complete" 2>/dev/null || true
            else
                ALL_FAILED=$((ALL_FAILED + 1))
                gum style --foreground 196 "  ❌ [R${ROUND} ${TASK_NUM}/$TOTAL_ALL] $LABEL — failed" 2>/dev/null || true
            fi
            echo ""
        done

        echo ""
        printf '%s\n' \
            "" \
            "  🏁 RUN ALL COMPLETE$(${LOOP_MODE} && echo " — Round $ROUND")" \
            "" \
            "  ✅ Passed:  $ALL_OK / $TOTAL_ALL" \
            "  ❌ Failed:  $ALL_FAILED" \
            "" \
        | (gum style \
            --border rounded \
            --border-foreground "$( [[ $ALL_FAILED -eq 0 ]] && echo 46 || echo 196 )" \
            --foreground "$( [[ $ALL_FAILED -eq 0 ]] && echo 46 || echo 214 )" \
            --bold \
            --padding "0 2" \
            --margin "0 0" 2>/dev/null || cat)

        if ! $LOOP_MODE; then
            echo ""
            echo -e "${DIM}Press Enter to close${RESET}"
            read -r
            break
        fi

        # Continuous mode: countdown with abort option
        echo ""
        gum style --foreground 214 --bold "🔁 Continuous mode — Round $((ROUND + 1)) in 10 seconds"
        gum style --foreground 242 "Press Ctrl+C to stop, or wait to continue..."
        echo ""

        if ! gum spin --spinner dot --title "Waiting 10s before next round..." -- sleep 10; then
            echo ""
            gum style --foreground 46 "⏹ Stopped after $ROUND round(s)."
            echo ""
            echo -e "${DIM}Press Enter to close${RESET}"
            read -r
            break
        fi

        done
        exit 0
    fi

    RUN_COUNT=0
    while true; do
        RUN_COUNT=$((RUN_COUNT + 1))
        echo ""
        if $LOOP_MODE; then
            gum style --foreground 46 --bold "▶ Run #$RUN_COUNT — Launching research pipeline..."
        else
            gum style --foreground 46 --bold "▶ Launching research pipeline..."
        fi
        [[ "$DATA_MODE" == "mydata" ]] && \
            gum style --foreground 242 --italic "  🔒 Solo mode — results stay local by default"
        echo ""

        TASK=$(parameterize_task "$TASK")
        nat run --config_file "$CONFIG" --input "$TASK" 2>&1 | tee -a "$LOG"

        echo ""
        gum style --foreground 46 "✅ Run #$RUN_COUNT complete."

        # Offer R2 contribution for My Data private runs
        [[ "${DATA_MODE:-public}" == "mydata" ]] && offer_r2_contribution

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
    ;;

    esac
    done
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

LABCLAW_SPECIES="human"
DOMAINS=("Cancer — Find mutations, predict immune targets" "Rare Disease — Analyze genetic variants for diagnosis" "Drug Discovery — Screen molecules, predict effectiveness" "Veterinary — Cancer & variants for dogs and cats" "Custom Task — Type your own question" "Genesis Mode — Run EVERY task across ALL domains (20 runs)")
select domain in "${DOMAINS[@]}"; do
    case "$REPLY" in
        1) ITEMS=("${CANCER_TASKS[@]}"); break ;;
        2) ITEMS=("${RARE_TASKS[@]}"); break ;;
        3) ITEMS=("${DRUG_TASKS[@]}"); break ;;
        4)
            echo ""
            echo -e "${BOLD}Which animal?${RESET}"
            echo "  1) Dog (Canine) — CanFam3.1, DLA alleles"
            echo "  2) Cat (Feline) — felCat9, FLA alleles"
            read -rp "Choice [1]: " _vet_choice
            case "${_vet_choice:-1}" in
                2) LABCLAW_SPECIES="cat"; ITEMS=("${FELINE_TASKS[@]}") ;;
                *) LABCLAW_SPECIES="dog"; ITEMS=("${CANINE_TASKS[@]}") ;;
            esac
            break
            ;;
        5)
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
        6)
            ALL_TASKS=()
            ALL_LABELS=()
            ALL_DOMAINS=()
            for t in "${CANCER_TASKS[@]}"; do
                _skip_local_task "${t#*|}" && continue
                ALL_TASKS+=("${t#*|}")
                raw="${t%%|*}"; ALL_LABELS+=("${raw%% ~*}")
                ALL_DOMAINS+=("Cancer")
            done
            for t in "${DRUG_TASKS[@]}"; do
                _skip_local_task "${t#*|}" && continue
                ALL_TASKS+=("${t#*|}")
                raw="${t%%|*}"; ALL_LABELS+=("${raw%% ~*}")
                ALL_DOMAINS+=("Drug Discovery")
            done
            for t in "${RARE_TASKS[@]}"; do
                _skip_local_task "${t#*|}" && continue
                ALL_TASKS+=("${t#*|}")
                raw="${t%%|*}"; ALL_LABELS+=("${raw%% ~*}")
                ALL_DOMAINS+=("Rare Disease")
            done
            for t in "${CANINE_TASKS[@]}"; do
                _skip_local_task "${t#*|}" && continue
                ALL_TASKS+=("${t#*|}")
                raw="${t%%|*}"; ALL_LABELS+=("${raw%% ~*}")
                ALL_DOMAINS+=("Veterinary 🐕")
            done
            for t in "${FELINE_TASKS[@]}"; do
                _skip_local_task "${t#*|}" && continue
                ALL_TASKS+=("${t#*|}")
                raw="${t%%|*}"; ALL_LABELS+=("${raw%% ~*}")
                ALL_DOMAINS+=("Veterinary 🐈")
            done
            TOTAL=${#ALL_TASKS[@]}

            # ── Data source picker (fallback) ─────────────────────
            DATA_FILES=$(detect_data_files)
            FILE_COUNT=0
            [[ -n "$DATA_FILES" ]] && FILE_COUNT=$(echo "$DATA_FILES" | wc -l)

            echo ""
            if [[ "$FILE_COUNT" -gt 0 ]]; then
                echo -e "${DIM}📂 Found $FILE_COUNT data file(s) in data/${RESET}"
            fi
            echo ""

            echo -e "${BOLD}Where should the data come from?${RESET}"
            PS3="Choice: "
            DATA_SOURCE_OPTS=("Public databases — TCGA, ClinVar, ChEMBL" "My data — files in data/")
            select ds in "${DATA_SOURCE_OPTS[@]}"; do
                case "$REPLY" in
                    1) DATA_MODE="public"; break ;;
                    2) DATA_MODE="mydata"; break ;;
                    *) echo "Invalid choice." ;;
                esac
            done

            if [[ "$DATA_MODE" == "mydata" ]]; then
                GENESIS_DATA_SUFFIX="Use uploaded files in data/ for analysis. Focus on the patient's own data."
                DATA_SOURCE_LABEL="📁 My data — files in data/"

                echo ""
                if [[ "$FILE_COUNT" -gt 0 ]]; then
                    echo -e "${GREEN}  ✅ Found $FILE_COUNT file(s) in data/${RESET}"
                    echo "$DATA_FILES" | head -8 | while read -r f; do
                        echo -e "     $(basename "$f")"
                    done
                    [[ $(echo "$DATA_FILES" | wc -l) -gt 8 ]] && \
                        echo "     … and $(($(echo "$DATA_FILES" | wc -l) - 8)) more"
                else
                    echo -e "${YELLOW}  ⚠️  No data files found yet${RESET}"
                fi
                echo ""
                echo -e "  ${BOLD}Put your files in:${RESET}  data/"
                echo ""
                echo -e "  ${DIM}Supported formats:${RESET}"
                echo -e "  ${DIM}  Genomics    .vcf .bam .fastq .fastq.gz${RESET}"
                echo -e "  ${DIM}  Sequences   .fasta .fa${RESET}"
                echo -e "  ${DIM}  Structures  .pdb${RESET}"
                echo -e "  ${DIM}  Compounds   .sdf${RESET}"
                echo -e "  ${DIM}  Tables      .csv .tsv${RESET}"
                echo ""
            else
                GENESIS_DATA_SUFFIX="Use public databases (TCGA/ClinVar/ChEMBL) for data sourcing."
                DATA_SOURCE_LABEL="🌐 Public databases — TCGA, ClinVar, ChEMBL"
            fi

            echo ""
            echo -e "${YELLOW}══════════════════════════════════════════════════${RESET}"
            echo -e "${YELLOW}  🚀 G E N E S I S   M O D E${RESET}"
            echo -e "${YELLOW}══════════════════════════════════════════════════${RESET}"
            echo -e "  $TOTAL tasks · 5 domains · $DATA_SOURCE_LABEL"
            echo ""

            _EXEC_PICK_FB=1
            while [[ $_EXEC_PICK_FB -eq 1 ]]; do
            _EXEC_PICK_FB=0

            echo -e "${BOLD}Execution mode:${RESET}"
            PARALLEL_OPTS=("1 — Sequential" "3 — Fast parallel" "6 — Max throughput" "12 — All at once" "999 — Continuous batch (Vast.ai pool, loops until budget)")
            select po in "${PARALLEL_OPTS[@]}"; do
                case "$REPLY" in
                    1) PARALLEL=1; break ;; 2) PARALLEL=3; break ;;
                    3) PARALLEL=6; break ;; 4) PARALLEL=12; break ;;
                    5) PARALLEL=999; break ;;
                    *) echo "Invalid choice." ;;
                esac
            done
            if [[ $PARALLEL -ge 100 ]]; then
                BATCH_MODE=1
                CONTINUOUS_BATCH=1
                echo ""
                echo -e "${DIM}Each task is one research job (e.g. tumor analysis, drug screen).${RESET}"
                echo -e "${DIM}Tasks are queued and distributed across your GPU pool.${RESET}"
                echo ""
                echo -e "${BOLD}How many research tasks per cycle?${RESET}"
                TASK_OPTS=("← Back" "25 tasks" "50 tasks" "100 tasks" "250 tasks" "500 tasks" "Custom")
                select _tp in "${TASK_OPTS[@]}"; do
                    case "$REPLY" in
                        1) break ;; 2) BATCH_COUNT=25; break ;; 3) BATCH_COUNT=50; break ;;
                        4) BATCH_COUNT=100; break ;; 5) BATCH_COUNT=250; break ;;
                        6) BATCH_COUNT=500; break ;; 7) BATCH_COUNT=custom; break ;;
                        *) echo "Invalid choice." ;;
                    esac
                done
                if [[ "$_tp" == *"Back"* ]]; then _EXEC_PICK_FB=1; continue; fi
                if [[ "$BATCH_COUNT" == "custom" ]]; then
                    read -rp "Enter task count (1-500) [100]: " BATCH_COUNT
                    BATCH_COUNT="${BATCH_COUNT:-100}"
                    if ! [[ "$BATCH_COUNT" =~ ^[0-9]+$ ]] || [[ "$BATCH_COUNT" -lt 1 ]]; then
                        BATCH_COUNT=100
                    elif [[ "$BATCH_COUNT" -gt 500 ]]; then
                        BATCH_COUNT=500
                        echo -e "${RED}  ⚠️  Capped to 500 tasks (budget protection)${RESET}"
                    fi
                fi
                REC_POOL=$((BATCH_COUNT / 10))
                [[ $REC_POOL -lt 1 ]] && REC_POOL=1
                [[ $REC_POOL -gt 20 ]] && REC_POOL=20
                echo ""
                echo -e "${DIM}GPU instances run tasks in parallel — more = faster but each costs ~\$0.50/hr.${RESET}"
                echo -e "${DIM}Aim for ~10 tasks per instance.${RESET}"
                echo ""
                echo -e "${BOLD}How many Vast.ai GPU instances?${RESET}"
                POOL_OPTS=("← Back" "Recommended: $REC_POOL (for $BATCH_COUNT tasks)" "1 instance" "2 instances" "5 instances" "10 instances" "20 instances" "Custom")
                select _pp in "${POOL_OPTS[@]}"; do
                    case "$REPLY" in
                        1) break ;; 2) POOL_SIZE=$REC_POOL; break ;;
                        3) POOL_SIZE=1; break ;; 4) POOL_SIZE=2; break ;;
                        5) POOL_SIZE=5; break ;; 6) POOL_SIZE=10; break ;;
                        7) POOL_SIZE=20; break ;; 8) POOL_SIZE=custom; break ;;
                        *) echo "Invalid choice." ;;
                    esac
                done
                if [[ "$_pp" == *"Back"* ]]; then _EXEC_PICK_FB=1; continue; fi
                if [[ "$POOL_SIZE" == "custom" ]]; then
                    read -rp "Enter instance count (1-20) [$REC_POOL]: " POOL_SIZE
                    POOL_SIZE="${POOL_SIZE:-$REC_POOL}"
                    if ! [[ "$POOL_SIZE" =~ ^[0-9]+$ ]] || [[ "$POOL_SIZE" -lt 1 ]]; then
                        POOL_SIZE=$REC_POOL
                    elif [[ "$POOL_SIZE" -gt 20 ]]; then
                        POOL_SIZE=20
                        echo -e "${RED}  ⚠️  Capped to 20 instances (budget protection)${RESET}"
                    fi
                fi
                TOTAL="$BATCH_COUNT"
                MODE_LABEL="continuous batch ($POOL_SIZE instances, loops until budget)"
                EST_COST=$(python3 -c "print(f'\${(int(\"$POOL_SIZE\") * 0.50 * 0.5):.2f}')" 2>/dev/null || echo "?")
                echo ""
                echo -e "${YELLOW}  🔄 Continuous: $BATCH_COUNT tasks/cycle → $POOL_SIZE instances (est. ~\$$EST_COST/cycle)${RESET}"
            else
                BATCH_MODE=0
                [[ $PARALLEL -eq 1 ]] && MODE_LABEL="sequential" || MODE_LABEL="$PARALLEL parallel"
            fi
            done  # end _EXEC_PICK_FB loop

            # ── Budget picker (Vast.ai batch mode — fallback) ─────────
            if [[ "${BATCH_MODE:-0}" -eq 1 ]]; then
                API_BALANCE=$(get_vast_balance)
                VAST_SPENT=$(psql -p 5433 -d opencurelabs -t -A -c \
                    "SELECT COALESCE(SUM(total_cost), 0) FROM vast_spend" 2>/dev/null || echo "0")
                AVAILABLE=$(python3 -c "print(f'{max(0, float(\"$API_BALANCE\") - float(\"$VAST_SPENT\")):.0f}')" 2>/dev/null || echo "$API_BALANCE")

                echo ""
                if python3 -c "exit(0 if float('$AVAILABLE') > 0 else 1)" 2>/dev/null; then
                    echo -e "${YELLOW}  💰 Vast.ai — \$$API_BALANCE balance, \$$VAST_SPENT spent this session${RESET}"
                    echo ""
                    echo -e "${BOLD}How much to spend on this run?${RESET}"

                    BUDGET_MENU=()
                    for amt in 5 10 25 50; do
                        if python3 -c "exit(0 if $amt <= float('$AVAILABLE') else 1)" 2>/dev/null; then
                            case $amt in
                                5)  BUDGET_MENU+=("\$5  — Quick test") ;;
                                10) BUDGET_MENU+=("\$10 — Small run") ;;
                                25) BUDGET_MENU+=("\$25 — Medium run") ;;
                                50) BUDGET_MENU+=("\$50 — Big run") ;;
                            esac
                        fi
                    done
                    BUDGET_MENU+=("\$$AVAILABLE — Full send (entire balance)")
                    BUDGET_MENU+=("Custom amount")

                    PS3="Budget: "
                    select bc in "${BUDGET_MENU[@]}"; do
                        case "$bc" in
                            *"Custom"*)
                                read -rp "Enter budget in USD (1-$AVAILABLE): " VAST_BUDGET
                                if ! [[ "$VAST_BUDGET" =~ ^[0-9]+\.?[0-9]*$ ]]; then
                                    VAST_BUDGET="$AVAILABLE"
                                elif python3 -c "exit(0 if float('$VAST_BUDGET') > float('$AVAILABLE') else 1)" 2>/dev/null; then
                                    VAST_BUDGET="$AVAILABLE"
                                    echo -e "${RED}  ⚠️  Capped to \$$AVAILABLE${RESET}"
                                elif python3 -c "exit(0 if float('$VAST_BUDGET') < 1 else 1)" 2>/dev/null; then
                                    VAST_BUDGET=1
                                fi
                                break ;;
                            "")
                                echo "Invalid choice." ;;
                            *)
                                VAST_BUDGET=$(echo "$bc" | grep -oP '^\$\K[0-9]+')
                                break ;;
                        esac
                    done

                    export VAST_AI_BUDGET="$VAST_BUDGET"
                    echo ""
                    echo -e "${GREEN}  🔒 Budget locked: \$$VAST_BUDGET — continuous until exhausted${RESET}"
                else
                    VAST_BUDGET=0
                    echo -e "${RED}  ⚠️  No Vast.ai balance — will run once locally${RESET}"
                fi
            else
                # Local modes — fetch balance for loop control
                API_BALANCE=$(get_vast_balance)
                VAST_BUDGET="$API_BALANCE"
            fi

            echo ""
            read -rp "Launch Genesis Mode? ($TOTAL tasks, $MODE_LABEL) [y/N] " genesis_confirm
            case "$genesis_confirm" in
                [yY]*)
                    GENESIS_TOTAL_OK=0
                    GENESIS_TOTAL_FAILED=0
                    GENESIS_START=$(date +%s)
                    ROUND=0

                    export LABCLAW_COMPUTE=local
                    [[ "$DATA_MODE" == "mydata" ]] && export OPENCURELABS_MODE=solo || export OPENCURELABS_MODE=contribute

                    if [[ "${BATCH_MODE:-0}" -eq 1 ]]; then
                        export LABCLAW_COMPUTE=vast_ai
                        echo ""
                        echo -e "${YELLOW}  🔄 Continuous batch: $BATCH_COUNT tasks/cycle → $POOL_SIZE instances${RESET}"
                        echo ""

                        BATCH_LOG="$PROJECT_DIR/logs/batch-$(date +%Y%m%d-%H%M%S).log"

                        BATCH_CMD=(python3 -m agentiq_labclaw.compute.batch_dispatcher
                            --count "$BATCH_COUNT"
                            --pool-size "$POOL_SIZE"
                            --max-cost 0.50
                            --config "$PROJECT_DIR/config/research_tasks.yaml"
                        )
                        if [[ "${CONTINUOUS_BATCH:-0}" -eq 1 ]]; then
                            BATCH_CMD+=(--continuous)
                            if [[ -n "${VAST_AI_BUDGET:-}" ]] && [[ "$VAST_AI_BUDGET" != "0" ]]; then
                                BATCH_CMD+=(--budget "$VAST_AI_BUDGET")
                            fi
                        fi

                        "${BATCH_CMD[@]}" 2>&1 | tee "$BATCH_LOG"

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
                                GENESIS_TASK="${ALL_TASKS[$i]} $GENESIS_DATA_SUFFIX Deploy 3 parallel agents. Use Vast.ai cloud GPU for compute."
                                GENESIS_TASK=$(parameterize_task "$GENESIS_TASK")
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
                                    GENESIS_TASK="${ALL_TASKS[$i]} $GENESIS_DATA_SUFFIX Deploy 3 parallel agents. Use Vast.ai cloud GPU for compute."
                                    GENESIS_TASK=$(parameterize_task "$GENESIS_TASK")
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

                    # ── Teardown persistent pool instances ───────────────
                    echo -e "  🧹 Tearing down Vast.ai pool instances..."
                    python3 -c "
from agentiq_labclaw.compute.vast_dispatcher import teardown_all_instances
teardown_all_instances()
" 2>&1 | sed 's/^/  /' || true

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

if [[ "$DATA_MODE" == "mydata" ]]; then
    echo ""
    if [[ "$FILE_COUNT" -gt 0 ]]; then
        echo -e "${GREEN}  ✅ Found $FILE_COUNT file(s) in data/${RESET}"
        echo "$DATA_FILES" | head -8 | while read -r f; do
            echo -e "     $(basename "$f")"
        done
        [[ $(echo "$DATA_FILES" | wc -l) -gt 8 ]] && \
            echo "     … and $(($(echo "$DATA_FILES" | wc -l) - 8)) more"
    else
        echo -e "${YELLOW}  ⚠️  No data files found yet${RESET}"
    fi
    echo ""
    echo -e "  ${BOLD}Put your files in:${RESET}  data/"
    echo ""
    echo -e "  ${DIM}Supported formats:${RESET}"
    echo -e "  ${DIM}  Genomics    .vcf .bam .fastq .fastq.gz${RESET}"
    echo -e "  ${DIM}  Sequences   .fasta .fa${RESET}"
    echo -e "  ${DIM}  Structures  .pdb${RESET}"
    echo -e "  ${DIM}  Compounds   .sdf${RESET}"
    echo -e "  ${DIM}  Tables      .csv .tsv${RESET}"
    echo ""
fi

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
if [[ "${DATA_MODE:-public}" == "public" ]]; then
    case "${SELECTED_LABEL:-}" in
        "Train Drug Predictor"|"Screen Drug Candidates"|"Predict Protein Shape"|"Predict Target Shape")
            echo ""
            read -rp "Use cloud GPU (Vast.ai)? [y/N] " vast_confirm
            case "$vast_confirm" in
                [yY]*) USE_VAST="yes" ;;
            esac
            ;;
    esac
fi

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
# Solo mode: My Data runs are private — only PDF publisher fires locally.
[[ "$DATA_MODE" == "mydata" ]] && export OPENCURELABS_MODE=solo || export OPENCURELABS_MODE=contribute
# Species routing — propagated to all LabClaw skills via environment
export LABCLAW_SPECIES="${LABCLAW_SPECIES:-human}"
[[ "$LABCLAW_SPECIES" != "human" ]] && TASK="$TASK species=$LABCLAW_SPECIES."

RUN_COUNT=0
while true; do
    RUN_COUNT=$((RUN_COUNT + 1))
    echo ""
    if $LOOP_MODE; then
        echo -e "${GREEN}▶ Run #$RUN_COUNT — Launching research pipeline...${RESET}"
    else
        echo -e "${GREEN}▶ Launching research pipeline...${RESET}"
    fi
    [[ "$DATA_MODE" == "mydata" ]] && echo -e "${DIM}  🔒 Solo mode — results stay local by default${RESET}"
    echo ""

    TASK=$(parameterize_task "$TASK")
    nat run --config_file "$CONFIG" --input "$TASK" 2>&1 | tee -a "$LOG"

    echo ""
    echo -e "${GREEN}✅ Run #$RUN_COUNT complete.${RESET}"

    # Offer R2 contribution for My Data private runs
    [[ "${DATA_MODE:-public}" == "mydata" ]] && offer_r2_contribution

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
