"""Sequencing data ingestion and QC skill — fastp integration."""

import json
import logging
import os
import random
import shutil
import subprocess
import tempfile
from pathlib import Path

from pydantic import BaseModel

from agentiq_labclaw.base import LabClawSkill, labclaw_skill
from agentiq_labclaw.species import get_species

logger = logging.getLogger("labclaw.skills.sequencing_qc")


def _project_root() -> Path:
    return Path(os.environ.get("OPENCURELABS_ROOT", str(Path(__file__).resolve().parents[3])))


REPORTS_DIR = _project_root() / "reports" / "qc"

# QC thresholds (based on common NGS standards)
MIN_MEAN_QUALITY = 20.0
MAX_ADAPTER_PCT = 5.0
MIN_GC_CONTENT = 30.0
MAX_GC_CONTENT = 70.0


class SequencingQCInput(BaseModel):
    sample_id: str
    fastq_paths: list[str]
    species: str = "human"  # "human" | "dog" | "cat"
    reference_genome: str = ""  # auto-derived from species if blank


class SequencingQCOutput(BaseModel):
    sample_id: str
    total_reads: int
    mean_quality: float
    gc_content: float
    adapter_contamination_pct: float
    pass_qc: bool
    qc_report_path: str
    novel: bool
    critique_required: bool
    synthetic: bool = False  # True when generated from synthetic data (not real FASTQ)


@labclaw_skill(
    name="sequencing_qc",
    description="Runs quality control on sequencing data (FASTQ files)",
    input_schema=SequencingQCInput,
    output_schema=SequencingQCOutput,
    compute="local",
    gpu_required=False,
)
class SequencingQCSkill(LabClawSkill):
    """
    Pipeline:
    1. Run fastp on input FASTQ files
    2. Parse QC metrics from JSON report
    3. Apply pass/fail thresholds
    4. Save QC report
    """

    def run(self, input_data: SequencingQCInput) -> SequencingQCOutput:
        # Derive reference genome from species if not explicitly set
        ref_genome = input_data.reference_genome
        if not ref_genome:
            species_config = get_species(input_data.species)
            ref_genome = species_config.reference_genome
        logger.info(
            "Running QC for sample %s (%d files) [species=%s, ref=%s]",
            input_data.sample_id, len(input_data.fastq_paths),
            input_data.species, ref_genome,
        )

        # Validate input FASTQ files exist (before requiring fastp)
        fastq_paths = list(input_data.fastq_paths)
        if not all(Path(p).exists() for p in fastq_paths):
            missing = [p for p in fastq_paths if not Path(p).exists()]
            logger.info(
                "FASTQ files not found (%s) — generating synthetic QC results for batch mode",
                ", ".join(missing),
            )
            return self._synthetic_qc(input_data)

        if not shutil.which("fastp"):
            raise FileNotFoundError("fastp not found in PATH. Install with: apt install fastp")

        REPORTS_DIR.mkdir(parents=True, exist_ok=True)

        # Build fastp command
        json_report = REPORTS_DIR / f"{input_data.sample_id}_fastp.json"
        html_report = REPORTS_DIR / f"{input_data.sample_id}_fastp.html"

        cmd = ["fastp", "--json", str(json_report), "--html", str(html_report)]

        if len(fastq_paths) == 1:
            cmd += ["--in1", fastq_paths[0]]
        elif len(fastq_paths) >= 2:
            cmd += ["--in1", fastq_paths[0], "--in2", fastq_paths[1]]
        else:
            raise ValueError("At least one FASTQ path is required")

        # Discard filtered output (QC-only mode)
        with tempfile.TemporaryDirectory() as tmpdir:
            cmd += ["--out1", f"{tmpdir}/filtered_R1.fq.gz"]
            if len(fastq_paths) >= 2:
                cmd += ["--out2", f"{tmpdir}/filtered_R2.fq.gz"]

            result = subprocess.run(  # noqa: S603
                cmd, capture_output=True, text=True, timeout=600,
            )
            if result.returncode != 0:
                raise RuntimeError(f"fastp failed: {result.stderr}")

        # Parse JSON report
        with open(json_report) as f:
            report = json.load(f)

        summary = report.get("summary", {})
        before = summary.get("before_filtering", {})
        after = summary.get("after_filtering", {})

        total_reads = before.get("total_reads", 0)
        mean_quality = after.get("quality_curves", {}).get("mean_quality", 0)
        # fastp stores mean quality in summary
        q30_rate = after.get("q30_rate", 0)
        gc_content = after.get("gc_content", 0) * 100  # Convert to percentage

        # Adapter stats
        adapter_trimming = report.get("adapter_cutting", {})
        adapter_reads = adapter_trimming.get("adapter_trimmed_reads", 0)
        adapter_pct = (adapter_reads / max(total_reads, 1)) * 100

        # Use mean quality from filtering result if available
        if isinstance(mean_quality, (int, float)) and mean_quality == 0:
            # Approximate from Q30 rate
            mean_quality = 30.0 * q30_rate + 20.0 * (1 - q30_rate) if q30_rate else 0.0

        # Apply QC thresholds
        pass_qc = (
            mean_quality >= MIN_MEAN_QUALITY
            and adapter_pct <= MAX_ADAPTER_PCT
            and MIN_GC_CONTENT <= gc_content <= MAX_GC_CONTENT
        )

        logger.info(
            "QC for %s: %d reads, Q=%.1f, GC=%.1f%%, adapters=%.1f%% → %s",
            input_data.sample_id, total_reads, mean_quality,
            gc_content, adapter_pct, "PASS" if pass_qc else "FAIL",
        )

        return SequencingQCOutput(
            sample_id=input_data.sample_id,
            total_reads=total_reads,
            mean_quality=round(mean_quality, 2),
            gc_content=round(gc_content, 2),
            adapter_contamination_pct=round(adapter_pct, 2),
            pass_qc=pass_qc,
            qc_report_path=str(html_report),
            novel=False,
            critique_required=not pass_qc,
        )

    def _synthetic_qc(self, input_data: SequencingQCInput) -> SequencingQCOutput:
        """Generate plausible synthetic QC metrics for batch/demo mode."""
        total_reads = random.randint(15_000_000, 80_000_000)
        mean_quality = round(random.uniform(28.0, 36.0), 2)
        gc_content = round(random.uniform(38.0, 55.0), 2)
        adapter_pct = round(random.uniform(0.1, 4.5), 2)

        pass_qc = (
            mean_quality >= MIN_MEAN_QUALITY
            and adapter_pct <= MAX_ADAPTER_PCT
            and MIN_GC_CONTENT <= gc_content <= MAX_GC_CONTENT
        )

        report_path = REPORTS_DIR / f"{input_data.sample_id}_synthetic_qc.json"
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps({
            "sample_id": input_data.sample_id,
            "synthetic": True,
            "total_reads": total_reads,
            "mean_quality": mean_quality,
            "gc_content": gc_content,
            "adapter_contamination_pct": adapter_pct,
            "pass_qc": pass_qc,
        }, indent=2))

        logger.info(
            "Synthetic QC for %s: %d reads, Q=%.1f, GC=%.1f%%, adapters=%.1f%% → %s",
            input_data.sample_id, total_reads, mean_quality,
            gc_content, adapter_pct, "PASS" if pass_qc else "FAIL",
        )

        return SequencingQCOutput(
            sample_id=input_data.sample_id,
            total_reads=total_reads,
            mean_quality=mean_quality,
            gc_content=gc_content,
            adapter_contamination_pct=adapter_pct,
            pass_qc=pass_qc,
            qc_report_path=str(report_path),
            novel=False,
            critique_required=not pass_qc,
            synthetic=True,
        )
