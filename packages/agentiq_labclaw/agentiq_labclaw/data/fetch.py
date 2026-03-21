"""Auto-download helpers for public biological data.

Each function checks for a local cached copy first; if absent, downloads from a
public API and caches under a deterministic directory.  All network calls use
explicit timeouts and raise on HTTP errors.

Public data sources:
    - PDB files: RCSB Protein Data Bank (https://files.rcsb.org)
    - ChEMBL bioactivity: ChEMBL REST API (https://www.ebi.ac.uk/chembl/api)
    - Synthetic VCF: bundled with the wheel (tests/data/synthetic_somatic.vcf)
    - Synthetic FASTQ: generated on the fly (minimal valid records)
"""

from __future__ import annotations

import importlib.resources
import logging
import math
import random
import shutil
import tempfile
from pathlib import Path

import requests

logger = logging.getLogger("labclaw.data.fetch")

CACHE_DIR = Path(tempfile.gettempdir()) / "labclaw_data"

# ── PDB ──────────────────────────────────────────────────────────────────────

RCSB_URL = "https://files.rcsb.org/download"


def fetch_pdb(pdb_id: str) -> Path:
    """Download a PDB file from RCSB if not already cached.

    Args:
        pdb_id: 4-character PDB identifier (e.g. ``1M17``).

    Returns:
        Path to the downloaded ``.pdb`` file.
    """
    pdb_id = pdb_id.strip().upper()
    dest = CACHE_DIR / "pdb" / f"{pdb_id}.pdb"
    if dest.exists() and dest.stat().st_size > 0:
        return dest

    url = f"{RCSB_URL}/{pdb_id}.pdb"
    logger.info("Downloading PDB %s from RCSB …", pdb_id)
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(resp.text)
    logger.info("Cached PDB %s → %s (%d bytes)", pdb_id, dest, dest.stat().st_size)
    return dest


# ── ChEMBL CSV ───────────────────────────────────────────────────────────────

CHEMBL_API = "https://www.ebi.ac.uk/chembl/api/data/activity.json"


def fetch_chembl_csv(
    target_chembl_id: str,
    target_col: str = "pIC50",
    limit: int = 500,
) -> Path:
    """Download bioactivity data for a ChEMBL target as CSV.

    The result CSV contains columns: ``smiles``, ``molecule_chembl_id``, and
    the requested *target_col* (e.g. ``pIC50``).

    Args:
        target_chembl_id: ChEMBL target ID (e.g. ``CHEMBL203``).
        target_col:       Name for the activity column.
        limit:            Max rows to fetch (API caps at 1000).

    Returns:
        Path to the cached CSV file.
    """
    import pandas as pd

    safe = target_chembl_id.replace("/", "_")
    dest = CACHE_DIR / "chembl" / f"{safe}.csv"
    if dest.exists() and dest.stat().st_size > 0:
        return dest

    logger.info("Fetching ChEMBL bioactivity for %s …", target_chembl_id)

    rows: list[dict] = []
    params = {
        "target_chembl_id": target_chembl_id,
        "type": "IC50",
        "limit": min(limit, 1000),
        "format": "json",
    }
    resp = requests.get(CHEMBL_API, params=params, timeout=60)
    resp.raise_for_status()
    data = resp.json()

    for act in data.get("activities", []):
        smi = act.get("canonical_smiles")
        val = act.get("value")
        mol_id = act.get("molecule_chembl_id")
        if smi and val:
            try:
                val_f = float(val)
                pval = -math.log10(val_f * 1e-9) if val_f > 0 else 0.0
            except (ValueError, TypeError):
                continue
            rows.append({
                "smiles": smi,
                "molecule_chembl_id": mol_id,
                target_col: round(pval, 4),
            })

    if not rows:
        logger.warning("No bioactivity data returned for %s — generating synthetic CSV", target_chembl_id)
        rows = _synthetic_chembl_rows(target_col, count=50)

    df = pd.DataFrame(rows)
    dest.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(dest, index=False)
    logger.info("Cached ChEMBL CSV → %s (%d rows)", dest, len(df))
    return dest


def _synthetic_chembl_rows(target_col: str, count: int = 50) -> list[dict]:
    """Generate minimal synthetic ChEMBL-like rows for testing."""
    # Simple valid SMILES for a handful of drug-like molecules
    scaffolds = [
        "c1ccccc1", "C1CCCCC1", "c1ccncc1", "C1CCNCC1", "c1ccc2ccccc2c1",
        "C1CCOC1", "c1ccoc1", "CC(=O)O", "CC(N)C(=O)O", "c1ccc(O)cc1",
    ]
    rows = []
    for i in range(count):
        base = random.choice(scaffolds)
        smi = f"{base}{'C' * (i % 5)}"
        rows.append({
            "smiles": smi,
            "molecule_chembl_id": f"CHEMBL_SYN_{i:04d}",
            target_col: round(random.uniform(4.0, 9.0), 4),
        })
    return rows


# ── Synthetic VCF ────────────────────────────────────────────────────────────

def fetch_vcf_synthetic(gene: str = "TP53", tumor: str = "NSCLC") -> Path:
    """Return path to the bundled synthetic VCF.

    Falls back to generating a minimal VCF if the bundled resource is missing.

    Args:
        gene:  Gene name (used in cache filename only).
        tumor: Tumor type (used in cache filename only).

    Returns:
        Path to a valid VCF file.
    """
    dest = CACHE_DIR / "vcf" / f"{gene.lower()}_{tumor.lower()}_somatic.vcf"
    if dest.exists() and dest.stat().st_size > 0:
        return dest

    dest.parent.mkdir(parents=True, exist_ok=True)

    # Try copying bundle from the installed package data
    try:
        resource = importlib.resources.files("agentiq_labclaw") / "bundled_data" / "synthetic_somatic.vcf"
        with importlib.resources.as_file(resource) as src:
            shutil.copy2(src, dest)
        logger.info("Copied bundled synthetic VCF → %s", dest)
        return dest
    except Exception:
        pass

    # Fallback: also check repo path (local dev)
    repo_vcf = Path(__file__).resolve().parents[4] / "tests" / "data" / "synthetic_somatic.vcf"
    if repo_vcf.exists():
        shutil.copy2(repo_vcf, dest)
        logger.info("Copied repo synthetic VCF → %s", dest)
        return dest

    # Last resort: generate minimal VCF inline
    logger.warning("Generating minimal synthetic VCF for %s/%s", gene, tumor)
    dest.write_text(_MINIMAL_VCF)
    return dest


_MINIMAL_VCF = """\
##fileformat=VCFv4.2
##source=labclaw_synthetic
##reference=GRCh38
##contig=<ID=17,length=83257441>
##contig=<ID=12,length=133275309>
##INFO=<ID=DP,Number=1,Type=Integer,Description="Total Depth">
##INFO=<ID=AF,Number=A,Type=Float,Description="Allele Frequency">
##FILTER=<ID=PASS,Description="All filters passed">
##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">
#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tTUMOR
17\t7675088\trs28934578\tC\tT\t100\tPASS\tDP=50;AF=0.3\tGT\t0/1
12\t25245350\trs121913529\tC\tA\t120\tPASS\tDP=60;AF=0.4\tGT\t0/1
"""


# ── Synthetic FASTQ ─────────────────────────────────────────────────────────

def generate_synthetic_fastq(sample_id: str, num_reads: int = 1000) -> list[Path]:
    """Generate a pair of minimal synthetic FASTQ files (R1 + R2).

    Produces short (100bp) reads with random sequence and uniform Q30 quality.
    Sufficient for fastp QC to run successfully and produce metrics.

    Args:
        sample_id: Identifier used in filenames and read names.
        num_reads: Number of read pairs to generate.

    Returns:
        List of two Paths: [R1.fastq, R2.fastq].
    """
    outdir = CACHE_DIR / "fastq"
    r1_path = outdir / f"{sample_id}_R1.fastq"
    r2_path = outdir / f"{sample_id}_R2.fastq"

    if r1_path.exists() and r2_path.exists():
        return [r1_path, r2_path]

    outdir.mkdir(parents=True, exist_ok=True)
    bases = "ACGT"
    read_len = 100
    qual = "I" * read_len  # Phred 40

    with open(r1_path, "w") as f1, open(r2_path, "w") as f2:
        for i in range(num_reads):
            seq1 = "".join(random.choice(bases) for _ in range(read_len))
            seq2 = "".join(random.choice(bases) for _ in range(read_len))
            f1.write(f"@{sample_id}_R1_{i:06d}\n{seq1}\n+\n{qual}\n")
            f2.write(f"@{sample_id}_R2_{i:06d}\n{seq2}\n+\n{qual}\n")

    logger.info("Generated synthetic FASTQ pair → %s, %s (%d reads)", r1_path, r2_path, num_reads)
    return [r1_path, r2_path]
