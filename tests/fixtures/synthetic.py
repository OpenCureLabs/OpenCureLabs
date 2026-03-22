"""Synthetic data generators for tests only.

These were originally in agentiq_labclaw.data.fetch — relocated here so that
synthetic data can never be generated in production code paths.
"""

from __future__ import annotations

import logging
import random
import shutil
import tempfile
from pathlib import Path

logger = logging.getLogger("labclaw.tests.synthetic")

CACHE_DIR = Path(tempfile.gettempdir()) / "labclaw_data"

# ── Synthetic ChEMBL rows ───────────────────────────────────────────────────


def synthetic_chembl_rows(target_col: str, count: int = 50) -> list[dict]:
    """Generate minimal synthetic ChEMBL-like rows for testing."""
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


def fetch_vcf_synthetic(gene: str = "TP53", tumor: str = "NSCLC") -> Path:
    """Return a synthetic VCF for testing.

    Copies from tests/data/ if available, otherwise generates inline.
    """
    dest = CACHE_DIR / "vcf" / f"{gene.lower()}_{tumor.lower()}_somatic.vcf"
    if dest.exists() and dest.stat().st_size > 0:
        return dest

    dest.parent.mkdir(parents=True, exist_ok=True)

    # Try copying from repo tests/data/
    repo_vcf = Path(__file__).resolve().parents[2] / "data" / "synthetic_somatic.vcf"
    if repo_vcf.exists():
        shutil.copy2(repo_vcf, dest)
        logger.info("Copied repo synthetic VCF → %s", dest)
        return dest

    # Fallback: generate minimal VCF inline
    logger.warning("Generating minimal synthetic VCF for %s/%s", gene, tumor)
    dest.write_text(_MINIMAL_VCF)
    return dest


# ── Synthetic FASTQ ──────────────────────────────────────────────────────────


def generate_synthetic_fastq(sample_id: str, num_reads: int = 1000) -> list[Path]:
    """Generate a pair of minimal synthetic FASTQ files (R1 + R2).

    Produces short (100bp) reads with random sequence and uniform Q30 quality.
    Sufficient for fastp QC to run successfully and produce metrics.
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
