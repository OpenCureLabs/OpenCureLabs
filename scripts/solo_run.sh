#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
#  OpenCure Labs — Solo Run
#
#  Run a private analysis on your own data files without the full dashboard.
#  Results are saved locally to reports/. No data leaves your machine by default.
#
#  Usage:
#    ./scripts/solo_run.sh                    # Auto-detect files in data/
#    ./scripts/solo_run.sh data/tumor.vcf     # Analyse a specific file
#    ./scripts/solo_run.sh data/reads.fastq   # Sequencing QC + neoantigen pipeline
#
#  After the run you will be asked if you want to contribute anonymized
#  scientific findings to the OpenCure Labs public dataset. Your raw files
#  and personal information are never uploaded — only the result summary.
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CONFIG="coordinator/labclaw_workflow.yaml"
LOG="logs/solo_run.log"

cd "$PROJECT_DIR"
source .venv/bin/activate 2>/dev/null || true

if [[ -f "$PROJECT_DIR/.env" ]]; then
    set -a; source "$PROJECT_DIR/.env"; set +a
fi

CYAN='\033[1;96m' GREEN='\033[1;92m' YELLOW='\033[1;93m'
RED='\033[1;91m'  DIM='\033[2m'       BOLD='\033[1m' RESET='\033[0m'

HAS_GUM=false
command -v gum &>/dev/null && HAS_GUM=true

# ── Classify a file by extension ─────────────────────────────────────────────
classify_file() {
    local file="$1"
    case "${file,,}" in
        *.vcf)                           echo "variant_pathogenicity|Assess variant pathogenicity (ClinVar + CADD scoring)" ;;
        *.fastq|*.fastq.gz|*.fq|*.fq.gz) echo "sequencing_qc+neoantigen|Sequencing QC → Neoantigen prediction" ;;
        *.bam)                           echo "sequencing_qc+neoantigen|Sequencing QC → Neoantigen prediction" ;;
        *.fasta|*.fa)                    echo "structure_prediction|Protein structure prediction (ESMFold/AlphaFold)" ;;
        *.pdb)                           echo "molecular_docking|Molecular docking — screen ligands against this structure" ;;
        *.sdf)                           echo "qsar|QSAR model training — predict bioactivity" ;;
        *.csv|*.tsv)                     echo "qsar|QSAR / expression analysis" ;;
        *)                               echo "" ;;
    esac
}

# ── Auto-detect the best file in data/ ───────────────────────────────────────
auto_detect_file() {
    for pattern in "*.vcf" "*.fastq" "*.fastq.gz" "*.fq.gz" "*.bam" "*.fasta" "*.fa" "*.pdb" "*.sdf"; do
        local f
        f=$(find "$PROJECT_DIR/data" -type f -name "$pattern" 2>/dev/null | head -1)
        [[ -n "$f" ]] && echo "$f" && return
    done
}

# ── Build task string from file + skill ──────────────────────────────────────
build_task() {
    local file="$1" skill="$2"
    local basename
    basename=$(basename "$file")

    case "$skill" in
        variant_pathogenicity)
            echo "Analyze variants for pathogenicity and gene-disease associations. "\
                 "Cross-reference ClinVar and CADD. Input file: $file."
            ;;
        sequencing_qc+neoantigen)
            echo "Run sequencing quality control on $file, then predict neoantigens "\
                 "from any somatic variants found. Run the full neoantigen pipeline."
            ;;
        structure_prediction)
            echo "Predict protein structure for the sequence in $file using "\
                 "ESMFold or AlphaFold. Return the 3D structure and confidence scores."
            ;;
        molecular_docking)
            echo "Perform molecular docking using the receptor structure in $file. "\
                 "Screen default compound library and rank hits by binding affinity."
            ;;
        qsar)
            echo "Train a QSAR model on the compounds or data in $file. "\
                 "Compute molecular descriptors and predict bioactivity."
            ;;
        *)
            echo "Analyze the file $file and produce a research report."
            ;;
    esac
}

# ── Post-run R2 opt-in prompt ─────────────────────────────────────────────────
offer_r2_contribution() {
    local last_result="$PROJECT_DIR/reports/last_result.json"
    [[ -f "$last_result" ]] || return 0

    echo ""
    if $HAS_GUM; then
        gum style --foreground 39 --bold "🌐 Contribute to OpenCure Labs?"
        gum style --foreground 242 "Results saved in reports/.  Optionally share anonymized scientific"
        gum style --foreground 242 "findings with the global dataset at pub.opencurelabs.ai."
        gum style --foreground 242 "Your raw files and personal data are never uploaded."
        echo ""
        if gum confirm "Contribute anonymized findings?" \
            --affirmative "Yes, contribute" --negative "No, keep private" \
            --default=false; then
            gum spin --spinner dot --title "Publishing to global dataset..." -- \
                PROJECT_DIR="$PROJECT_DIR" python3 - <<'PYEOF' 2>/dev/null
import sys, json, os, pathlib
sys.path.insert(0, os.environ['PROJECT_DIR'] + '/packages/agentiq_labclaw')
os.environ['OPENCURELABS_MODE'] = 'contribute'
from agentiq_labclaw.publishers.r2_publisher import R2Publisher
f = pathlib.Path(os.environ['PROJECT_DIR']) / 'reports' / 'last_result.json'
data = json.loads(f.read_text())
result = R2Publisher().publish_result(
    data['skill_name'], data['result'],
    novel=data['result'].get('novel', False), status='published'
)
if result:
    print(result.get('url', ''))
PYEOF
            && gum style --foreground 46 "✅ Contributed! View at https://opencurelabs.ai" \
            || gum style --foreground 196 "Could not reach ingest server — results are safe locally."
        fi
    else
        echo -e "${CYAN}── Contribute to OpenCure Labs? ──${RESET}"
        echo "Results saved in reports/. You can optionally share anonymized findings."
        echo "Raw files and personal data are never uploaded."
        echo ""
        read -rp "Contribute findings to opencurelabs.ai? [y/N] " _contrib
        case "$_contrib" in
            [yY]*)
                echo "Publishing..."
                PROJECT_DIR="$PROJECT_DIR" python3 - <<'PYEOF' 2>/dev/null
import sys, json, os, pathlib
sys.path.insert(0, os.environ['PROJECT_DIR'] + '/packages/agentiq_labclaw')
os.environ['OPENCURELABS_MODE'] = 'contribute'
from agentiq_labclaw.publishers.r2_publisher import R2Publisher
f = pathlib.Path(os.environ['PROJECT_DIR']) / 'reports' / 'last_result.json'
data = json.loads(f.read_text())
result = R2Publisher().publish_result(
    data['skill_name'], data['result'],
    novel=data['result'].get('novel', False), status='published'
)
if result:
    print('Published:', result.get('url', ''))
PYEOF
                echo -e "${GREEN}✅ Contributed! View at https://opencurelabs.ai${RESET}"
                ;;
        esac
    fi
}

# ═════════════════════════════════════════════════════════════════════════════
#  MAIN
# ═════════════════════════════════════════════════════════════════════════════

# ── Header ───────────────────────────────────────────────────────────────────
if $HAS_GUM; then
    gum style \
        --border double --border-foreground 39 \
        --padding "0 2" --bold \
        "🧬  OpenCure Labs — Solo Analysis"
else
    echo -e "${CYAN}══════════════════════════════════════════════════${RESET}"
    echo -e "${CYAN}  🧬 OpenCure Labs — Solo Analysis${RESET}"
    echo -e "${CYAN}══════════════════════════════════════════════════${RESET}"
fi
echo ""
echo -e "${DIM}Results stay on your machine. You choose whether to share findings.${RESET}"
echo ""

# ── Resolve target file ───────────────────────────────────────────────────────
TARGET_FILE=""
if [[ $# -gt 0 ]]; then
    TARGET_FILE="$1"
    if [[ ! -f "$TARGET_FILE" ]]; then
        echo -e "${RED}File not found: $TARGET_FILE${RESET}"
        exit 1
    fi
else
    echo -e "${DIM}Scanning data/ for files...${RESET}"
    TARGET_FILE=$(auto_detect_file)
    if [[ -z "$TARGET_FILE" ]]; then
        echo ""
        echo -e "${YELLOW}No data files found in data/.${RESET}"
        echo ""
        echo "Drop your files into the data/ directory, then run:"
        echo "  ./scripts/solo_run.sh                    # auto-detect"
        echo "  ./scripts/solo_run.sh data/tumor.vcf     # specific file"
        echo ""
        echo "Supported formats:"
        echo "  .vcf               → Variant pathogenicity analysis"
        echo "  .fastq / .bam      → Sequencing QC + neoantigen prediction"
        echo "  .fasta             → Protein structure prediction"
        echo "  .pdb               → Molecular docking"
        echo "  .sdf               → QSAR / bioactivity prediction"
        exit 1
    fi
    echo -e "${GREEN}Found:${RESET} $(basename "$TARGET_FILE")"
fi

# ── Classify and suggest pipeline ────────────────────────────────────────────
CLASSIFICATION=$(classify_file "$TARGET_FILE")
if [[ -z "$CLASSIFICATION" ]]; then
    echo -e "${YELLOW}Unknown file type. Running general analysis.${RESET}"
    SKILL="general"
    SKILL_LABEL="General analysis"
else
    SKILL=$(echo "$CLASSIFICATION" | cut -d'|' -f1)
    SKILL_LABEL=$(echo "$CLASSIFICATION" | cut -d'|' -f2)
fi

echo ""
if $HAS_GUM; then
    gum style --foreground 46 --bold "Suggested pipeline:"
    gum style --foreground 255 "  $(basename "$TARGET_FILE")  →  $SKILL_LABEL"
    echo ""
    if ! gum confirm "Run this analysis?" \
        --affirmative "Run" --negative "Cancel"; then
        echo "Cancelled."
        exit 0
    fi
else
    echo -e "${BOLD}Suggested pipeline:${RESET}"
    echo "  $(basename "$TARGET_FILE")  →  $SKILL_LABEL"
    echo ""
    read -rp "Run this analysis? [Y/n] " _confirm
    case "${_confirm:-y}" in
        [nN]*) echo "Cancelled."; exit 0 ;;
    esac
fi

# ── Optional: extra context from user ────────────────────────────────────────
EXTRA=""
case "$SKILL" in
    sequencing_qc+neoantigen)
        echo ""
        if $HAS_GUM; then
            EXTRA=$(gum input \
                --placeholder "HLA type if known (leave blank to auto-detect)" \
                --prompt "HLA: " --prompt.foreground 46 --width 60) || EXTRA=""
        else
            read -rp "HLA type if known (leave blank to auto-detect): " EXTRA
        fi
        [[ -n "$EXTRA" ]] && EXTRA=" HLA type: $EXTRA."
        ;;
    variant_pathogenicity)
        echo ""
        if $HAS_GUM; then
            EXTRA=$(gum input \
                --placeholder "Gene name if known (leave blank)" \
                --prompt "Gene: " --prompt.foreground 46 --width 40) || EXTRA=""
        else
            read -rp "Gene name if known (leave blank): " EXTRA
        fi
        [[ -n "$EXTRA" ]] && EXTRA=" Gene: $EXTRA."
        ;;
esac

# ── Build and launch ─────────────────────────────────────────────────────────
TASK="$(build_task "$TARGET_FILE" "$SKILL")$EXTRA"

echo ""
if $HAS_GUM; then
    gum style --foreground 46 --bold "▶ Launching solo analysis..."
    gum style --foreground 242 --italic "  🔒 Solo mode — results stay local by default"
else
    echo -e "${GREEN}▶ Launching solo analysis...${RESET}"
    echo -e "${DIM}  🔒 Solo mode — results stay local by default${RESET}"
fi
echo ""

mkdir -p logs reports
export OPENCURELABS_MODE=solo
export LABCLAW_COMPUTE=local

nat run --config_file "$CONFIG" --input "$TASK" 2>&1 | tee -a "$LOG"

echo ""
if $HAS_GUM; then
    gum style --foreground 46 --bold "✅ Analysis complete."
    gum style --foreground 242 "Reports saved to: reports/"
else
    echo -e "${GREEN}✅ Analysis complete.${RESET}"
    echo -e "${DIM}Reports saved to: reports/${RESET}"
fi

# ── Post-run contribution prompt ──────────────────────────────────────────────
offer_r2_contribution

echo ""
echo -e "${DIM}Done. Press Enter to exit.${RESET}"
read -r
