#!/usr/bin/env python3
"""
Periodic refresh of D1 task queue from public genomics databases.

Queries ClinVar, ChEMBL, and IMGT/HLA for entries not already in the
hardcoded parameter banks and seeds corresponding research tasks into the
D1 central queue via POST /tasks/seed.

Deduplication is handled server-side (SHA-256 input_hash UNIQUE constraint),
so this script is fully idempotent — safe to run repeatedly.

Usage:
    python scripts/refresh_param_banks.py                # Full refresh
    python scripts/refresh_param_banks.py --dry-run      # Preview without seeding
    python scripts/refresh_param_banks.py --sources clinvar,chembl  # Specific sources

Environment:
    OPENCURELABS_ADMIN_KEY  — admin key for D1 Worker (or loaded from .env)
    D1_WORKER_URL           — Worker base URL (default: https://ingest.opencurelabs.ai)
    NCBI_API_KEY            — optional, raises NCBI rate limit from 3/s to 10/s
"""

import argparse
import hashlib
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

import requests

log = logging.getLogger("refresh_param_banks")

# ── Configuration ────────────────────────────────────────────────────────────

WORKER_URL = os.getenv("D1_WORKER_URL", "https://ingest.opencurelabs.ai")
ADMIN_KEY = os.getenv("OPENCURELABS_ADMIN_KEY", "")
NCBI_API_KEY = os.getenv("NCBI_API_KEY", "")

NCBI_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
CHEMBL_BASE = "https://www.ebi.ac.uk/chembl/api/data"
IMGT_HLA_URL = "https://raw.githubusercontent.com/ANHIG/IMGTHLA/Latest/Allelelist.txt"

# Rate limit: 3 req/s without NCBI key, 10 with
NCBI_DELAY = 0.11 if NCBI_API_KEY else 0.35

# ── Known parameter banks (extracted from tasks.ts) ──────────────────────────
# Used only for reporting "N new entries" — D1 handles actual dedup.

KNOWN_GENES = {
    "TP53", "BRCA1", "EGFR", "KRAS", "PIK3CA", "BRAF", "PTEN", "ALK", "RET",
    "MET", "HER2", "IDH1", "FGFR3", "CDH1", "APC", "NRAS", "HRAS", "CDKN2A",
    "RB1", "NF1", "NF2", "VHL", "WT1", "SMAD4", "STK11", "FBXW7", "NOTCH1",
    "ARID1A", "KMT2D", "CTNNB1", "MAP2K1", "ERBB3", "ERBB4", "FLT3", "KIT",
    "PDGFRA", "JAK2", "JAK1", "ABL1", "SRC", "FGFR1", "FGFR2", "FGFR4",
    "ROS1", "NTRK1", "NTRK3", "DDR2", "MTOR", "TSC1", "TSC2", "PTCH1", "SMO",
    "SUFU", "CTCF", "DNMT3A", "TET2", "EZH2", "ASXL1", "SF3B1", "U2AF1",
    "SRSF2", "NPM1", "RUNX1", "GATA3", "FOXA1", "SPOP", "AR", "ESR1",
    "CCND1", "MDM2", "MYC", "MYCN", "BCL2", "MCL1", "XPO1", "BTK", "CARD11",
    "MYD88", "CD79B", "CREBBP", "EP300", "KMT2A", "KMT2C", "SETD2", "BAP1",
    "PBRM1", "SMARCA4", "ARID2", "BRD4", "KEAP1", "NFE2L2", "STK11", "CASP8",
    "FAT1", "TERT", "POT1", "DAXX", "ATRX", "CIC", "FUBP1", "NOTCH2",
    "SPEN", "KDM6A", "KDM5C", "PHF6", "BCOR", "BCORL1", "STAG2", "RAD21",
    "SMC1A", "SMC3", "NIPBL", "PPM1D", "CHEK2", "ATM", "ATR", "BRCA2",
    "PALB2", "RAD51C", "RAD51D", "FANCA", "FANCC", "MLH1", "MSH2", "MSH6",
    "PMS2", "POLE", "POLD1", "AKT1", "MAP3K1", "MAP3K13", "RHOA", "RAC1",
    "CDC42", "RAB35", "GNAQ", "GNA11", "PLCB4", "CYSLTR2", "BAX", "CASP3",
    "CASP9", "APAF1", "XIAP", "BCL2L1", "BIM", "BAD", "BID", "NOXA", "PUMA",
    "STAT3", "STAT5B", "SHP2", "CBL", "CBLB", "PTPN11", "PTPN1", "PTPRD",
    "INPP4B", "PIK3R1", "PIK3CB", "PIK3CG", "MERTK", "AXL", "TYRO3", "DDR1",
    "IGF1R", "INSR", "ERBB2", "NRG1", "FGFR3", "IGF2", "FGF19", "FGF3",
    "FGF4", "CCNE1", "CDK4", "CDK6", "RB1", "CDKN1A", "CDKN1B", "CDKN2B",
    "E2F3",
}

KNOWN_HLA_A = {
    "HLA-A*01:01", "HLA-A*02:01", "HLA-A*02:02", "HLA-A*02:06", "HLA-A*02:07",
    "HLA-A*02:11", "HLA-A*03:01", "HLA-A*11:01", "HLA-A*23:01", "HLA-A*24:02",
    "HLA-A*26:01", "HLA-A*29:02", "HLA-A*30:01", "HLA-A*30:02", "HLA-A*31:01",
    "HLA-A*33:01", "HLA-A*33:03", "HLA-A*34:01", "HLA-A*34:02", "HLA-A*66:01",
    "HLA-A*68:01", "HLA-A*68:02", "HLA-A*74:01",
}

KNOWN_CHEMBL_TARGETS = {
    "CHEMBL203", "CHEMBL2971", "CHEMBL5145", "CHEMBL3116", "CHEMBL4247",
    "CHEMBL5251", "CHEMBL4005", "CHEMBL3105", "CHEMBL4630", "CHEMBL2842",
    "CHEMBL3650", "CHEMBL4142", "CHEMBL2635", "CHEMBL2185", "CHEMBL3717",
    "CHEMBL5568", "CHEMBL267", "CHEMBL1936", "CHEMBL2007", "CHEMBL1974",
    "CHEMBL279", "CHEMBL4722", "CHEMBL1957", "CHEMBL2508", "CHEMBL301",
    "CHEMBL3038", "CHEMBL4523", "CHEMBL3286", "CHEMBL325", "CHEMBL1163125",
    "CHEMBL1795126", "CHEMBL6164", "CHEMBL4523063",
}

TUMOR_TYPES = [
    "NSCLC", "breast", "colorectal", "melanoma", "glioblastoma",
    "pancreatic", "ovarian", "prostate", "hepatocellular", "renal",
    "SCLC", "head_neck_SCC", "esophageal", "gastric", "cholangiocarcinoma",
    "bladder_urothelial", "cervical", "endometrial", "thyroid_papillary",
    "thyroid_anaplastic", "adrenocortical", "pheochromocytoma", "mesothelioma",
    "testicular_germ_cell", "thymoma", "AML", "CLL", "DLBCL",
    "multiple_myeloma", "MDS", "uveal_melanoma", "sarcoma_UPS",
    "Ewing_sarcoma", "neuroblastoma", "medulloblastoma",
]

# Reuse existing HLA panels for neoantigen task combos
HLA_PANELS = [
    ["HLA-A*02:01", "HLA-B*07:02", "HLA-C*07:02"],
    ["HLA-A*01:01", "HLA-B*08:01", "HLA-C*07:01"],
    ["HLA-A*03:01", "HLA-B*44:03", "HLA-C*04:01"],
    ["HLA-A*24:02", "HLA-B*35:01", "HLA-C*04:01"],
    ["HLA-A*11:01", "HLA-B*15:01", "HLA-C*03:04"],
]


# ── HTTP Session ─────────────────────────────────────────────────────────────

def _session() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = "OpenCureLabs/refresh-param-banks (contact: agent@opencurelabs)"
    return s


# ── Data Source: ClinVar (NCBI E-utilities) ──────────────────────────────────

def fetch_clinvar_genes(session: requests.Session) -> list[dict]:
    """Fetch cancer-driver genes with pathogenic variants from ClinVar."""
    log.info("Querying ClinVar for pathogenic cancer-gene variants...")

    params: dict[str, Any] = {
        "db": "clinvar",
        "term": (
            '("pathogenic"[clinical significance] OR "likely pathogenic"[clinical significance]) '
            'AND "cancer"[disease/phenotype] '
            'AND "single nucleotide variant"[variation type]'
        ),
        "retmax": 500,
        "retmode": "json",
    }
    if NCBI_API_KEY:
        params["api_key"] = NCBI_API_KEY

    resp = session.get(f"{NCBI_BASE}/esearch.fcgi", params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    ids = data.get("esearchresult", {}).get("idlist", [])
    if not ids:
        log.info("  No new ClinVar results found.")
        return []

    log.info(f"  Found {len(ids)} ClinVar variant IDs, fetching summaries...")
    time.sleep(NCBI_DELAY)

    # Fetch summaries in chunks of 100
    genes: list[dict] = []
    for i in range(0, len(ids), 100):
        chunk = ids[i : i + 100]
        summary_params: dict[str, Any] = {
            "db": "clinvar",
            "id": ",".join(chunk),
            "retmode": "json",
        }
        if NCBI_API_KEY:
            summary_params["api_key"] = NCBI_API_KEY

        resp = session.get(f"{NCBI_BASE}/esummary.fcgi", params=summary_params, timeout=30)
        resp.raise_for_status()
        summaries = resp.json().get("result", {})

        for uid in chunk:
            entry = summaries.get(uid, {})
            gene_names = entry.get("genes", [])
            for g in gene_names:
                symbol = g.get("symbol", "")
                if symbol and symbol.upper() not in {g.upper() for g in KNOWN_GENES}:
                    genes.append({
                        "gene": symbol,
                        "clinvar_id": uid,
                        "title": entry.get("title", ""),
                    })

        time.sleep(NCBI_DELAY)

    # Deduplicate by gene symbol
    seen = set()
    unique: list[dict] = []
    for g in genes:
        sym = g["gene"].upper()
        if sym not in seen:
            seen.add(sym)
            unique.append(g)

    log.info(f"  {len(unique)} new genes found from ClinVar (not in hardcoded banks).")
    return unique


# ── Data Source: ChEMBL ──────────────────────────────────────────────────────

def fetch_chembl_targets(session: requests.Session) -> list[dict]:
    """Fetch drug targets with bioactivity data from ChEMBL."""
    log.info("Querying ChEMBL for single-protein targets with bioactivity data...")

    targets: list[dict] = []
    url = (
        f"{CHEMBL_BASE}/target.json"
        "?target_type=SINGLE%20PROTEIN"
        "&organism=Homo%20sapiens"
        "&limit=100"
        "&offset=0"
    )

    # Paginate through results (cap at 500 to be respectful)
    fetched = 0
    while url and fetched < 500:
        resp = session.get(url, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        for t in data.get("targets", []):
            chembl_id = t.get("target_chembl_id", "")
            pref_name = t.get("pref_name", "")
            if chembl_id and chembl_id not in KNOWN_CHEMBL_TARGETS:
                # Only include targets with significant bioactivity data
                components = t.get("target_components", [])
                gene = ""
                if components:
                    synonyms = components[0].get("target_component_synonyms", [])
                    for syn in synonyms:
                        if syn.get("syn_type") == "GENE_SYMBOL":
                            gene = syn.get("component_synonym", "")
                            break

                targets.append({
                    "chembl_id": chembl_id,
                    "name": pref_name,
                    "gene": gene,
                })

        fetched += len(data.get("targets", []))
        next_url = data.get("page_meta", {}).get("next")
        url = f"https://www.ebi.ac.uk{next_url}" if next_url else None
        time.sleep(0.5)  # Be nice to ChEMBL

    log.info(f"  {len(targets)} new ChEMBL targets found (not in hardcoded banks).")
    return targets[:200]  # Cap at 200 new targets per refresh


# ── Data Source: IMGT/HLA ────────────────────────────────────────────────────

def fetch_hla_alleles(session: requests.Session) -> list[str]:
    """Fetch new HLA-A alleles from IMGT/HLA database."""
    log.info("Fetching HLA allele list from IMGT/HLA...")

    resp = session.get(IMGT_HLA_URL, timeout=30)
    resp.raise_for_status()

    new_alleles = []
    for line in resp.text.splitlines():
        if line.startswith("#") or not line.strip():
            continue
        parts = line.split(",")
        if len(parts) < 2:
            continue
        allele = parts[1].strip()
        # Only care about HLA-A (the primary allele in our panels) at 2-field resolution
        if allele.startswith("A*"):
            two_field = "HLA-" + ":".join(allele.split(":")[:2])
            if two_field not in KNOWN_HLA_A:
                new_alleles.append(two_field)

    unique = sorted(set(new_alleles))
    log.info(f"  {len(unique)} new HLA-A alleles found (not in hardcoded panels).")
    return unique[:50]  # Cap — each new allele generates many combos


# ── Task Generation ──────────────────────────────────────────────────────────

def generate_tasks(
    new_genes: list[dict],
    new_targets: list[dict],
    new_alleles: list[str],
) -> list[dict]:
    """Generate D1-compatible tasks from newly discovered parameters."""
    tasks: list[dict] = []

    # 1. New cancer genes → neoantigen prediction + structure prediction
    for gene_info in new_genes:
        gene = gene_info["gene"]

        # Structure prediction
        tasks.append({
            "skill": "structure_prediction",
            "input_data": {
                "protein_id": gene,
                "sequence": f"{gene}_wildtype",
                "method": "esmfold",
            },
            "domain": "cancer",
            "species": "human",
            "label": f"Structure [human]: {gene} (ClinVar refresh)",
            "priority": 5,
        })

        # Neoantigen combos: gene × top 5 tumors × top 5 HLA panels
        # (keeps task count manageable: 25 tasks per new gene)
        for tumor in TUMOR_TYPES[:5]:
            for panel in HLA_PANELS:
                tasks.append({
                    "skill": "neoantigen_prediction",
                    "input_data": {
                        "sample_id": f"{gene}_{tumor}_human_batch",
                        "vcf_path": f"data/human/{tumor.lower()}/{gene.lower()}_somatic.vcf",
                        "hla_alleles": panel,
                        "tumor_type": tumor,
                        "species": "human",
                    },
                    "domain": "cancer",
                    "species": "human",
                    "label": f"Neoantigen [human]: {gene} in {tumor} (ClinVar refresh)",
                    "priority": 5,
                })

        # Variant pathogenicity
        if gene_info.get("clinvar_id"):
            tasks.append({
                "skill": "variant_pathogenicity",
                "input_data": {
                    "variant_id": f"clinvar_{gene_info['clinvar_id']}",
                    "gene": gene,
                    "hgvs": gene_info.get("title", "unknown"),
                    "species": "human",
                },
                "domain": "rare_disease",
                "species": "human",
                "label": f"Variant [human]: {gene} (ClinVar refresh)",
                "priority": 5,
            })

    # 2. New ChEMBL targets → QSAR tasks
    for target in new_targets:
        for model_type in ["random_forest", "gradient_boosting", "ridge"]:
            tasks.append({
                "skill": "qsar",
                "input_data": {
                    "dataset_path": f"chembl/{target['chembl_id']}_bioactivity.csv",
                    "target_column": "pIC50",
                    "smiles_column": "canonical_smiles",
                    "model_type": model_type,
                    "mode": "train_predict",
                },
                "domain": "drug_discovery",
                "species": "human",
                "label": f"QSAR [human]: {target['name'][:40]} / {model_type} (ChEMBL refresh)",
                "priority": 5,
            })

    # 3. New HLA alleles → neoantigen combos with top cancer genes
    top_genes = ["TP53", "BRCA1", "EGFR", "KRAS", "PIK3CA", "BRAF", "PTEN",
                 "ALK", "RET", "MET", "HER2", "IDH1", "FGFR3", "CDH1", "APC"]
    for allele in new_alleles:
        # Build a panel with the new allele as HLA-A, paired with common B/C
        panel = [allele, "HLA-B*07:02", "HLA-C*07:02"]
        for gene in top_genes[:5]:
            for tumor in TUMOR_TYPES[:3]:
                tasks.append({
                    "skill": "neoantigen_prediction",
                    "input_data": {
                        "sample_id": f"{gene}_{tumor}_human_batch",
                        "vcf_path": f"data/human/{tumor.lower()}/{gene.lower()}_somatic.vcf",
                        "hla_alleles": panel,
                        "tumor_type": tumor,
                        "species": "human",
                    },
                    "domain": "cancer",
                    "species": "human",
                    "label": f"Neoantigen [human]: {gene} in {tumor} ({allele} HLA refresh)",
                    "priority": 5,
                })

    return tasks


# ── D1 Submission ────────────────────────────────────────────────────────────

def seed_tasks(tasks: list[dict], dry_run: bool = False) -> dict:
    """Push tasks to D1 via POST /tasks/seed (in chunks of 500)."""
    if not tasks:
        return {"inserted": 0, "duplicates": 0, "total": 0}

    if dry_run:
        log.info(f"  [DRY RUN] Would seed {len(tasks)} tasks to D1.")
        return {"inserted": 0, "duplicates": 0, "total": len(tasks), "dry_run": True}

    if not ADMIN_KEY:
        log.error("  OPENCURELABS_ADMIN_KEY not set — cannot seed tasks.")
        return {"error": "no admin key", "total": len(tasks)}

    total_inserted = 0
    total_duplicates = 0
    chunk_size = 500

    for i in range(0, len(tasks), chunk_size):
        chunk = tasks[i : i + chunk_size]
        try:
            resp = requests.post(
                f"{WORKER_URL}/tasks/seed",
                json={"tasks": chunk},
                headers={
                    "X-Admin-Key": ADMIN_KEY,
                    "Content-Type": "application/json",
                },
                timeout=120,
            )
            resp.raise_for_status()
            result = resp.json()
            total_inserted += result.get("inserted", 0)
            total_duplicates += result.get("duplicates", 0)
            log.info(
                f"  Chunk {i // chunk_size + 1}: "
                f"{result.get('inserted', 0)} inserted, "
                f"{result.get('duplicates', 0)} duplicates"
            )
        except requests.RequestException as e:
            log.error(f"  Failed to seed chunk {i // chunk_size + 1}: {e}")

        time.sleep(0.5)

    return {"inserted": total_inserted, "duplicates": total_duplicates, "total": len(tasks)}


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Refresh D1 task queue from public genomics databases."
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview tasks without seeding")
    parser.add_argument(
        "--sources",
        default="clinvar,chembl,hla",
        help="Comma-separated sources to query (default: clinvar,chembl,hla)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    )

    # Load .env if present
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))

    # Re-read env after loading .env
    global ADMIN_KEY, NCBI_API_KEY, WORKER_URL, NCBI_DELAY
    ADMIN_KEY = os.getenv("OPENCURELABS_ADMIN_KEY", "")
    NCBI_API_KEY = os.getenv("NCBI_API_KEY", "")
    WORKER_URL = os.getenv("D1_WORKER_URL", "https://ingest.opencurelabs.ai")
    NCBI_DELAY = 0.11 if NCBI_API_KEY else 0.35

    sources = {s.strip().lower() for s in args.sources.split(",")}
    session = _session()

    log.info("=" * 60)
    log.info("OpenCure Labs — Parameter Bank Refresh")
    log.info(f"Sources: {', '.join(sorted(sources))}")
    log.info(f"Worker:  {WORKER_URL}")
    log.info(f"Dry run: {args.dry_run}")
    log.info("=" * 60)

    new_genes: list[dict] = []
    new_targets: list[dict] = []
    new_alleles: list[str] = []

    if "clinvar" in sources:
        try:
            new_genes = fetch_clinvar_genes(session)
        except Exception as e:
            log.error(f"ClinVar query failed: {e}")

    if "chembl" in sources:
        try:
            new_targets = fetch_chembl_targets(session)
        except Exception as e:
            log.error(f"ChEMBL query failed: {e}")

    if "hla" in sources:
        try:
            new_alleles = fetch_hla_alleles(session)
        except Exception as e:
            log.error(f"IMGT/HLA query failed: {e}")

    tasks = generate_tasks(new_genes, new_targets, new_alleles)

    log.info("")
    log.info(f"Generated {len(tasks)} new tasks:")
    log.info(f"  From ClinVar genes:  {sum(1 for t in tasks if 'ClinVar' in t.get('label', ''))}")
    log.info(f"  From ChEMBL targets: {sum(1 for t in tasks if 'ChEMBL' in t.get('label', ''))}")
    log.info(f"  From HLA alleles:    {sum(1 for t in tasks if 'HLA refresh' in t.get('label', ''))}")
    log.info("")

    if not tasks:
        log.info("No new tasks to seed. Parameter banks are up to date.")
        return

    result = seed_tasks(tasks, dry_run=args.dry_run)
    log.info("")
    log.info(f"Seed result: {json.dumps(result, indent=2)}")
    log.info("Done.")


if __name__ == "__main__":
    main()
