#!/usr/bin/env python3
"""Generate synthetic somatic VCF files for all gene × tumor combinations.

Creates minimal VCFv4.2 files under data/human/{tumor}/{gene}_somatic.vcf
(and data/dog/, data/cat/ for veterinary species) so the neoantigen pipeline
has an input file for every task in the D1 queue.

Usage:
    python scripts/generate_vcfs.py            # default: all species
    python scripts/generate_vcfs.py --species human
    python scripts/generate_vcfs.py --dry-run  # just count, don't write
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

VCF_HEADER = """\
##fileformat=VCFv4.2
##source=OpenCureLabs-synthetic
##INFO=<ID=DP,Number=1,Type=Integer,Description="Read depth">
##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">
#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE
"""

# ── Human cancer genes (matches tasks.ts CANCER_GENES) ──────────────────────
HUMAN_GENES: list[tuple[str, str, str, str]] = [
    # gene, chrom, pos, ref>alt
    ("TP53", "chr17", "7674220", "C>T"),
    ("BRCA1", "chr17", "43094464", "G>A"),
    ("EGFR", "chr7", "55259515", "T>G"),
    ("KRAS", "chr12", "25245350", "C>A"),
    ("PIK3CA", "chr3", "179234297", "A>G"),
    ("BRAF", "chr7", "140753336", "A>T"),
    ("PTEN", "chr10", "87933147", "C>T"),
    ("ALK", "chr2", "29415640", "C>A"),
    ("RET", "chr10", "43609944", "C>T"),
    ("MET", "chr7", "116411990", "G>A"),
    ("HER2", "chr17", "39724775", "A>G"),
    ("IDH1", "chr2", "208248388", "C>T"),
    ("FGFR3", "chr4", "1803568", "G>C"),
    ("CDH1", "chr16", "68835675", "G>A"),
    ("APC", "chr5", "112175770", "C>T"),
    ("NRAS", "chr1", "115256529", "T>C"),
    ("HRAS", "chr11", "534242", "C>A"),
    ("CDKN2A", "chr9", "21971120", "C>T"),
    ("RB1", "chr13", "48367556", "G>A"),
    ("NF1", "chr17", "31252184", "C>T"),
    ("NF2", "chr22", "30032805", "G>A"),
    ("VHL", "chr3", "10149920", "G>A"),
    ("WT1", "chr11", "32413565", "C>T"),
    ("SMAD4", "chr18", "51065525", "C>T"),
    ("STK11", "chr19", "1219400", "G>A"),
    ("FBXW7", "chr4", "152326159", "C>T"),
    ("NOTCH1", "chr9", "139399360", "G>A"),
    ("ARID1A", "chr1", "26773594", "C>T"),
    ("KMT2D", "chr12", "49415854", "C>T"),
    ("CTNNB1", "chr3", "41224610", "T>C"),
    ("MAP2K1", "chr15", "66727455", "G>A"),
    ("ERBB3", "chr12", "56083807", "G>A"),
    ("ERBB4", "chr2", "212498867", "G>A"),
    ("FLT3", "chr13", "28034105", "A>G"),
    ("KIT", "chr4", "55593464", "A>T"),
    ("PDGFRA", "chr4", "55141055", "A>T"),
    ("JAK2", "chr9", "5073770", "G>T"),
    ("JAK1", "chr1", "64846780", "G>A"),
    ("ABL1", "chr9", "130862949", "C>T"),
    ("SRC", "chr20", "37399349", "G>A"),
    ("FGFR1", "chr8", "38285863", "A>G"),
    ("FGFR2", "chr10", "121520170", "C>T"),
    ("FGFR4", "chr5", "176520243", "G>A"),
    ("ROS1", "chr6", "117642522", "G>A"),
    ("NTRK1", "chr1", "156874568", "G>A"),
    ("NTRK3", "chr15", "88524924", "C>T"),
    ("DDR2", "chr1", "162685370", "G>A"),
    ("MTOR", "chr1", "11174395", "C>T"),
    ("TSC1", "chr9", "132903976", "C>T"),
    ("TSC2", "chr16", "2126314", "G>A"),
    ("PTCH1", "chr9", "98231058", "G>A"),
    ("SMO", "chr7", "128846308", "G>A"),
    ("SUFU", "chr10", "102526990", "C>T"),
    ("CTCF", "chr16", "67632413", "G>A"),
    ("DNMT3A", "chr2", "25234374", "G>A"),
    ("TET2", "chr4", "105243553", "C>T"),
    ("EZH2", "chr7", "148504856", "G>A"),
    ("ASXL1", "chr20", "31022292", "G>T"),
    ("SF3B1", "chr2", "197402110", "G>A"),
    ("U2AF1", "chr21", "44513783", "C>T"),
    ("SRSF2", "chr17", "74733099", "G>A"),
    ("NPM1", "chr5", "170837543", "C>T"),
    ("RUNX1", "chr21", "34788937", "G>A"),
    ("GATA3", "chr10", "8098509", "C>T"),
    ("FOXA1", "chr14", "37590985", "G>A"),
    ("SPOP", "chr17", "47701140", "G>A"),
    ("AR", "chrX", "67711614", "G>A"),
    ("ESR1", "chr6", "151842245", "G>A"),
    ("CCND1", "chr11", "69462910", "G>A"),
    ("MDM2", "chr12", "68817124", "G>A"),
    ("MYC", "chr8", "128748315", "G>A"),
    ("MYCN", "chr2", "16110614", "G>A"),
    ("BCL2", "chr18", "63123685", "G>A"),
    ("MCL1", "chr1", "150578425", "G>A"),
    ("XPO1", "chr2", "61496721", "G>A"),
    ("BTK", "chrX", "101360541", "G>A"),
    ("CARD11", "chr7", "2988470", "G>A"),
    ("MYD88", "chr3", "38141150", "T>C"),
    ("CD79B", "chr17", "63929526", "G>A"),
    ("CREBBP", "chr16", "3786745", "C>T"),
    ("EP300", "chr22", "41150648", "C>T"),
    ("KMT2A", "chr11", "118392508", "C>T"),
    ("KMT2C", "chr7", "152134282", "C>T"),
    ("SETD2", "chr3", "47057898", "C>T"),
    ("BAP1", "chr3", "52443449", "G>A"),
    ("PBRM1", "chr3", "52617589", "C>T"),
    ("SMARCA4", "chr19", "11097274", "G>A"),
    ("SMARCB1", "chr22", "24134560", "G>A"),
    ("SWI_SNF", "chr1", "26679610", "G>A"),
    ("KEAP1", "chr19", "10507331", "G>A"),
    ("NFE2L2", "chr2", "177234308", "G>A"),
    ("CASP8", "chr2", "201262061", "C>T"),
    ("FAT1", "chr4", "186631800", "G>A"),
    ("PPP2R1A", "chr19", "52228221", "C>T"),
    ("MAP3K1", "chr5", "56174679", "G>A"),
    ("MAP3K4", "chr6", "162011236", "G>A"),
    ("POLE", "chr12", "132624261", "C>T"),
    ("MSH2", "chr2", "47630556", "G>A"),
    ("MSH6", "chr2", "47783412", "G>A"),
    ("PMS2", "chr7", "6026871", "G>A"),
    ("MLH1", "chr3", "37089131", "G>A"),
    ("ATM", "chr11", "108202608", "C>T"),
    ("ATR", "chr3", "142220823", "G>A"),
    ("CHEK2", "chr22", "28695868", "G>A"),
    ("BRCA2", "chr13", "32911463", "T>G"),
    ("PALB2", "chr16", "23641310", "G>A"),
    ("RAD51C", "chr17", "58698786", "G>A"),
    ("CDK6", "chr7", "92462464", "G>A"),
    ("CDK12", "chr17", "39461871", "G>A"),
    ("CCNE1", "chr19", "29823652", "G>A"),
    ("TERT", "chr5", "1295228", "G>A"),
    ("ATRX", "chrX", "76950471", "G>A"),
    ("DAXX", "chr6", "33286355", "G>A"),
    ("CIC", "chr19", "42287874", "G>A"),
    ("FUBP1", "chr1", "77933072", "G>A"),
    ("KDM5C", "chrX", "53220408", "G>A"),
    ("KDM6A", "chrX", "44873099", "G>A"),
    ("PHF6", "chrX", "133547574", "G>A"),
    ("BCOR", "chrX", "39922359", "G>A"),
    ("BCORL1", "chrX", "129147612", "G>A"),
    ("STAG2", "chrX", "123197837", "G>A"),
    ("RAD21", "chr8", "117867834", "G>A"),
    ("SMC1A", "chrX", "53428147", "G>A"),
    ("ZRSR2", "chrX", "15828891", "G>A"),
    ("TP63", "chr3", "189604747", "G>A"),
    ("SOX9", "chr17", "72121020", "G>A"),
    ("MAX", "chr14", "65031219", "G>A"),
    ("MGA", "chr15", "41818854", "G>A"),
    ("RNF43", "chr17", "58356667", "G>A"),
    ("AXIN1", "chr16", "393821", "G>A"),
    ("APC2", "chr19", "1438768", "G>A"),
    ("TCF7L2", "chr10", "112998590", "G>A"),
    ("GNAS", "chr20", "58909365", "G>A"),
    ("GNA11", "chr19", "3094019", "C>T"),
    ("GNAQ", "chr9", "77794572", "C>T"),
    ("RAC1", "chr7", "6444172", "C>T"),
    ("RHOA", "chr3", "49396789", "G>A"),
    ("CDC42", "chr1", "22417990", "G>A"),
    ("PIK3R1", "chr5", "67589149", "G>A"),
    ("AKT1", "chr14", "104780214", "G>A"),
    ("AKT2", "chr19", "40230317", "G>A"),
    ("RICTOR", "chr5", "38953653", "G>A"),
    ("RPTOR", "chr17", "78929298", "G>A"),
    ("PTPN11", "chr12", "112856531", "G>A"),
    ("SHP2", "chr12", "112926261", "G>A"),
    ("CBL", "chr11", "119148908", "G>A"),
    ("CBLB", "chr3", "107272093", "G>A"),
    ("NRG1", "chr8", "31497272", "G>A"),
    ("ERBB2", "chr17", "39724775", "A>G"),
    ("IGF1R", "chr15", "98717498", "G>A"),
    ("VEGFA", "chr6", "43770209", "G>A"),
    ("KDR", "chr4", "55095264", "G>A"),
    ("FGF19", "chr11", "69218308", "G>A"),
    ("FGF3", "chr11", "69571337", "G>A"),
    ("FGF4", "chr11", "69582822", "G>A"),
    ("CCND3", "chr6", "41934973", "G>A"),
    ("CDK4", "chr12", "57747727", "G>A"),
    ("RBM10", "chrX", "47058498", "G>A"),
    ("U2AF2", "chr19", "55661636", "G>A"),
    ("IDH2", "chr15", "90088606", "C>T"),
    ("SDH_A", "chr5", "218356", "G>A"),
    ("SDH_B", "chr1", "17371320", "G>A"),
    ("SDH_C", "chr1", "161309956", "G>A"),
    ("SDH_D", "chr11", "112086955", "G>A"),
    ("FH", "chr1", "241660836", "G>A"),
    ("DICER1", "chr14", "95086222", "G>A"),
    ("DROSHA", "chr5", "31434916", "G>A"),
    ("EPHA3", "chr3", "89476283", "G>A"),
    ("EPHA5", "chr4", "65717620", "G>A"),
    ("EPHB1", "chr3", "134902301", "G>A"),
    ("LATS1", "chr6", "150001234", "G>A"),
    ("LATS2", "chr13", "21553421", "G>A"),
    ("YAP1", "chr11", "102054722", "G>A"),
    ("TAZ_WWTR1", "chr3", "149756116", "G>A"),
    ("NKX2_1", "chr14", "36516869", "G>A"),
    ("SOX2", "chr3", "181429690", "G>A"),
    ("PRDM1", "chr6", "106117044", "G>A"),
    ("IRF4", "chr6", "391739", "G>A"),
    ("TNFAIP3", "chr6", "138197822", "G>A"),
    ("B2M", "chr15", "44715432", "G>A"),
    ("HLA_A", "chr6", "29942470", "G>A"),
    ("HLA_B", "chr6", "31353872", "G>A"),
    ("JAK3", "chr19", "17935696", "G>A"),
    ("TYK2", "chr19", "10350276", "G>A"),
    ("STAT3", "chr17", "42322400", "G>A"),
    ("STAT5B", "chr17", "40372999", "G>A"),
    ("SOCS1", "chr16", "11254730", "G>A"),
    ("PTPRD", "chr9", "8313487", "G>A"),
    ("PTPRT", "chr20", "41498866", "G>A"),
    ("INPP4B", "chr4", "143543070", "G>A"),
    ("PIK3C2B", "chr1", "204424709", "G>A"),
    ("PIK3C3", "chr18", "39560368", "G>A"),
    ("RASA1", "chr5", "86602050", "G>A"),
    ("LZTR1", "chr22", "21343727", "G>A"),
    ("PPM1D", "chr17", "60665028", "G>A"),
    ("MUTYH", "chr1", "45332396", "G>A"),
    ("NTHL1", "chr16", "2041822", "G>A"),
    ("SMAD2", "chr18", "47841769", "G>A"),
    ("SMAD3", "chr15", "67063400", "G>A"),
    ("TGFBR2", "chr3", "30713126", "G>A"),
    ("ACVR1", "chr2", "158384001", "G>A"),
    ("BMP5", "chr6", "55665800", "G>A"),
    ("BMPR1A", "chr10", "86756617", "G>A"),
    ("AMER1", "chrX", "63413252", "G>A"),
    ("TRRAP", "chr7", "98516649", "G>A"),
    ("KANSL1", "chr17", "46025783", "G>A"),
    ("KAT6A", "chr8", "41790268", "G>A"),
    ("HDAC", "chr1", "32757608", "G>A"),
    ("SIRT1", "chr10", "67884607", "G>A"),
    ("BRD4", "chr19", "15349216", "G>A"),
    ("DOT1L", "chr19", "2165047", "G>A"),
    ("PRMT5", "chr14", "23356050", "G>A"),
    ("WRN", "chr8", "30890851", "G>A"),
    ("BLM", "chr15", "90717388", "G>A"),
    ("RECQL4", "chr8", "144514543", "G>A"),
    ("FANCA", "chr16", "89805015", "G>A"),
    ("FANCD2", "chr3", "10068098", "G>A"),
    ("RAD50", "chr5", "132556339", "G>A"),
    ("MRE11", "chr11", "94417771", "G>A"),
    ("NBN", "chr8", "89971435", "G>A"),
    ("XRCC1", "chr19", "43543580", "G>A"),
    ("ERCC2", "chr19", "45365065", "G>A"),
    ("XPC", "chr3", "14165356", "G>A"),
    ("DDB2", "chr11", "47217741", "G>A"),
    ("MGMT", "chr10", "129467108", "G>A"),
]

HUMAN_TUMOR_TYPES = [
    "NSCLC", "breast", "colorectal", "melanoma", "glioblastoma",
    "pancreatic", "ovarian", "prostate", "hepatocellular", "renal",
    "SCLC", "head_neck_SCC", "esophageal", "gastric", "cholangiocarcinoma",
    "bladder_urothelial", "cervical", "endometrial", "thyroid_papillary", "thyroid_anaplastic",
    "adrenocortical", "pheochromocytoma", "mesothelioma", "testicular_germ_cell", "thymoma",
    "AML", "CLL", "DLBCL", "multiple_myeloma", "MDS",
    "uveal_melanoma", "sarcoma_UPS", "Ewing_sarcoma", "neuroblastoma", "medulloblastoma",
]

CANINE_GENES = [
    ("BRAF", "chr16", "26835234", "A>T"),
    ("KIT", "chr13", "28001012", "G>A"),
    ("TP53", "chr5", "53824190", "G>A"),
    ("BRCA1", "chr17", "4523112", "C>T"),
    ("BRCA2", "chr11", "9941812", "G>A"),
    ("PTEN", "chr4", "50821099", "C>T"),
    ("MC1R", "chr5", "33924088", "G>A"),
    ("NRAS", "chr16", "35102234", "A>G"),
    ("PDGFRA", "chr13", "27990100", "G>T"),
    ("RAS", "chr7", "10000000", "G>A"),
    ("PIK3CA", "chr27", "14500210", "G>A"),
    ("EGFR", "chr18", "23100345", "G>A"),
    ("KRAS", "chr9", "45200120", "G>A"),
    ("APC", "chr3", "10000000", "G>A"),
    ("SETD2", "chr37", "8900234", "G>A"),
    ("CDKN2A", "chr11", "12340567", "G>A"),
    ("MDM2", "chr10", "88900123", "G>A"),
    ("RB1", "chr22", "33400890", "G>A"),
    ("MYC", "chr13", "44500120", "G>A"),
    ("BCL2", "chr1", "55600789", "G>A"),
]

CANINE_TUMOR_TYPES = [
    "mast_cell_tumor", "osteosarcoma", "lymphoma",
    "mammary_tumor", "melanoma", "hemangiosarcoma",
    "transitional_cell_carcinoma", "soft_tissue_sarcoma",
    "histiocytic_sarcoma", "nasal_carcinoma", "lung_carcinoma",
    "anal_sac_adenocarcinoma", "thyroid_carcinoma", "hepatocellular_carcinoma",
]

FELINE_GENES = [
    ("KIT", "chrB1", "41200123", "G>T"),
    ("TP53", "chrE2", "29823456", "G>A"),
    ("PDGFRA", "chrB3", "15023890", "A>G"),
    ("NRAS", "chrF2", "12340500", "C>T"),
    ("BRCA1", "chrB1", "44500321", "C>T"),
    ("MYC", "chrA3", "10000000", "G>A"),
    ("BRAF", "chrD1", "22300456", "G>A"),
    ("PIK3CA", "chrA1", "33100789", "G>A"),
    ("ERBB2", "chrE1", "11200345", "G>A"),
    ("KRAS", "chrC2", "44300567", "G>A"),
    ("PTEN", "chrB4", "55400123", "G>A"),
    ("APC", "chrA2", "66500234", "G>A"),
]

FELINE_TUMOR_TYPES = [
    "mammary_carcinoma", "mast_cell_tumor", "lymphoma",
    "squamous_cell_carcinoma", "vaccine_site_sarcoma",
    "intestinal_lymphoma", "intestinal_adenocarcinoma", "oral_SCC",
    "nasal_lymphoma", "hepatic_lymphoma",
]


def generate_vcf_content(gene: str, chrom: str, pos: str, ref_alt: str) -> str:
    """Generate a minimal VCF file body for a single gene's somatic mutation."""
    ref, alt = ref_alt.split(">")
    return (
        VCF_HEADER
        + f"{chrom}\t{pos}\t{gene}_somatic\t{ref}\t{alt}\t60\tPASS\tDP=100\tGT\t0/1\n"
    )


def generate_vcfs(
    species: str,
    genes: list[tuple[str, str, str, str]],
    tumor_types: list[str],
    dry_run: bool = False,
) -> int:
    """Generate VCF files for every gene × tumor combination. Returns count."""
    created = 0
    skipped = 0
    data_dir = PROJECT_ROOT / "data" / species

    for gene_name, chrom, pos, ref_alt in genes:
        content = generate_vcf_content(gene_name, chrom, pos, ref_alt)
        for tumor in tumor_types:
            vcf_dir = data_dir / tumor.lower()
            vcf_path = vcf_dir / f"{gene_name.lower()}_somatic.vcf"

            if vcf_path.exists():
                skipped += 1
                continue

            if dry_run:
                created += 1
                continue

            vcf_dir.mkdir(parents=True, exist_ok=True)
            vcf_path.write_text(content)
            created += 1

    return created, skipped


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic somatic VCFs")
    parser.add_argument("--species", choices=["human", "dog", "cat", "all"], default="all")
    parser.add_argument("--dry-run", action="store_true", help="Count files without writing")
    args = parser.parse_args()

    total_created = 0
    total_skipped = 0

    species_map = {
        "human": (HUMAN_GENES, HUMAN_TUMOR_TYPES),
        "dog": (CANINE_GENES, CANINE_TUMOR_TYPES),
        "cat": (FELINE_GENES, FELINE_TUMOR_TYPES),
    }

    targets = [args.species] if args.species != "all" else ["human", "dog", "cat"]

    for sp in targets:
        genes, tumors = species_map[sp]
        created, skipped = generate_vcfs(sp, genes, tumors, dry_run=args.dry_run)
        total_created += created
        total_skipped += skipped
        label = "(dry-run) " if args.dry_run else ""
        print(f"  {sp}: {label}{created} created, {skipped} already existed ({len(genes)} genes × {len(tumors)} tumors)")

    print(f"\nTotal: {total_created} VCFs {'would be ' if args.dry_run else ''}created, {total_skipped} skipped")


if __name__ == "__main__":
    main()
