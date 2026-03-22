#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
#  Download pyensembl genome annotation data for veterinary species
#
#  Must be run once before running dog/cat pipelines.
#  Human (GRCh38 release 110) is installed by the main setup script.
#
#  Usage:
#    bash scripts/download_ensembl_species.sh [--species dog|cat|all]
#
#  Requirements:
#    - pyensembl >= 2.3 (already in requirements.txt)
#    - ~4 GB disk space per species (GTF + FASTA from Ensembl FTP)
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"
source .venv/bin/activate 2>/dev/null || true

SPECIES="${1:---all}"
# Normalize "--species dog" style flag
[[ "$SPECIES" == "--species" ]] && SPECIES="${2:-all}"

download_species() {
    local name="$1" release="$2" pyensembl_name="$3"
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  Downloading Ensembl ${release} annotation for ${name}"
    echo "  pyensembl species key: ${pyensembl_name}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""

    if pyensembl install --release "$release" --species "$pyensembl_name"; then
        echo ""
        echo "  ✅ ${name} (Ensembl ${release}) — installed successfully"
    else
        echo ""
        echo "  ❌ ${name} (Ensembl ${release}) — download failed"
        echo "     Check https://ftp.ensembl.org/pub/release-${release}/ is accessible"
        return 1
    fi
}

case "${SPECIES}" in
    dog|canine)
        download_species "Dog (Canis lupus familiaris)" 112 "dog"
        ;;
    cat|feline)
        download_species "Cat (Felis catus)" 112 "cat"
        ;;
    all|--all)
        download_species "Dog (Canis lupus familiaris)" 112 "dog"
        download_species "Cat (Felis catus)" 112 "cat"
        ;;
    *)
        echo "Usage: $0 [dog|cat|all]"
        echo ""
        echo "Available species:"
        echo "  dog  — Canis lupus familiaris (CanFam3.1, Ensembl 112)"
        echo "  cat  — Felis catus (felCat9, Ensembl 112)"
        echo "  all  — Install both (default)"
        exit 1
        ;;
esac

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Done.  Verify with:"
echo "    python3 -c \"from pyensembl import EnsemblRelease; "
echo "                 r = EnsemblRelease(112, species='dog'); "
echo "                 print(r.genes_at_locus('chr16', 26835234))\""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
