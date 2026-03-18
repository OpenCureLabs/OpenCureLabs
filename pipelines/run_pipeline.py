"""Pipeline runner — execute multi-step scientific pipelines end-to-end.

Each pipeline is a sequence of LabClaw skills chained together.
Results are logged to PostgreSQL and optionally reviewed by Claude/Grok.

Usage:
    python pipelines/run_pipeline.py neoantigen --vcf data/sample.vcf --hla "HLA-A*02:01,HLA-B*07:02"
    python pipelines/run_pipeline.py variant_discovery --variant "chr17:7674220:C>T" --gene TP53
    python pipelines/run_pipeline.py drug_screen --smiles "CC(=O)Oc1ccccc1C(O)=O" --receptor data/target.pdb
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime

import psycopg2

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "packages", "agentiq_labclaw"))

DB_URL = os.environ.get("POSTGRES_URL", "dbname=opencurelabs port=5433")
logger = logging.getLogger("opencurelabs.pipeline")
logging.basicConfig(level=logging.INFO, format="%(name)s | %(levelname)s | %(message)s")


def get_conn():
    conn = psycopg2.connect(DB_URL)
    conn.autocommit = True
    return conn


def log_pipeline_start(pipeline_name: str) -> int | None:
    """Log pipeline start to DB and return pipeline_run_id."""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO pipeline_runs (pipeline_name, started_at, status) VALUES (%s, %s, 'running') RETURNING id",
            (pipeline_name, datetime.utcnow()),
        )
        run_id = cur.fetchone()[0]
        cur.close()
        conn.close()
        return run_id
    except Exception as e:
        logger.warning("Could not log pipeline start: %s", e)
        return None


def log_pipeline_end(run_id: int | None, status: str = "completed"):
    """Update pipeline run status."""
    if run_id is None:
        return
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            "UPDATE pipeline_runs SET completed_at = %s, status = %s WHERE id = %s",
            (datetime.utcnow(), status, run_id),
        )
        cur.close()
        conn.close()
    except Exception as e:
        logger.warning("Could not log pipeline end: %s", e)


def log_result(run_id: int | None, result_type: str, data: dict, novel: bool = False):
    """Log experiment result to DB."""
    if run_id is None:
        return
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO experiment_results (pipeline_run_id, result_type, result_data, novel, timestamp) "
            "VALUES (%s, %s, %s, %s, %s)",
            (run_id, result_type, json.dumps(data, default=str), novel, datetime.utcnow()),
        )
        cur.close()
        conn.close()
    except Exception as e:
        logger.warning("Could not log result: %s", e)


# ── Neoantigen Pipeline ─────────────────────────────────────────────────────


def run_neoantigen(args):
    """VCF → neoantigen prediction → report."""
    from agentiq_labclaw.skills.neoantigen import NeoantigenInput, NeoantigenSkill

    run_id = log_pipeline_start("neoantigen_discovery")
    logger.info("Starting neoantigen pipeline (run_id=%s)", run_id)

    try:
        hla_alleles = [a.strip() for a in args.hla.split(",")]
        inp = NeoantigenInput(
            sample_id=args.sample_id or os.path.basename(args.vcf),
            vcf_path=args.vcf,
            hla_alleles=hla_alleles,
            tumor_type=args.tumor_type or "unknown",
        )

        skill = NeoantigenSkill()
        result = skill.run(inp)

        logger.info(
            "Neoantigen pipeline complete: %d candidates, confidence=%.3f, novel=%s",
            len(result.candidates), result.confidence_score, result.novel,
        )

        log_result(run_id, "neoantigen_prediction", result.model_dump(), novel=result.novel)
        log_pipeline_end(run_id, "completed")
        return result

    except Exception as e:
        logger.error("Neoantigen pipeline failed: %s", e)
        log_pipeline_end(run_id, "failed")
        raise


# ── Variant Discovery Pipeline ───────────────────────────────────────────────


def run_variant_discovery(args):
    """Variant ID → ClinVar lookup → pathogenicity scoring → report."""
    from agentiq_labclaw.skills.variant_pathogenicity import VariantInput, VariantPathogenicitySkill

    run_id = log_pipeline_start("variant_discovery")
    logger.info("Starting variant discovery pipeline (run_id=%s)", run_id)

    try:
        inp = VariantInput(
            variant_id=args.variant,
            gene=args.gene,
            transcript=args.transcript,
        )

        skill = VariantPathogenicitySkill()
        result = skill.run(inp)

        logger.info(
            "Variant %s classified as %s (score=%.4f)",
            result.variant_id, result.classification, result.pathogenicity_score,
        )

        log_result(run_id, "variant_pathogenicity", result.model_dump(), novel=result.novel)

        # Generate report if pathogenic
        if result.classification in ("pathogenic", "likely_pathogenic"):
            try:
                from agentiq_labclaw.skills.report_generator import ReportGeneratorSkill, ReportInput

                report_inp = ReportInput(
                    title=f"Variant Pathogenicity Report — {result.variant_id}",
                    pipeline_run_id=run_id or 0,
                    sections=[
                        {"heading": "Variant Summary", "content": f"Gene: {result.gene}\nClassification: {result.classification}\nScore: {result.pathogenicity_score}"},
                        {"heading": "ClinVar", "content": f"Significance: {result.clinvar_significance or 'Not found'}"},
                        {"heading": "OMIM Associations", "content": json.dumps(result.omim_associations, indent=2)},
                    ],
                )
                report = ReportGeneratorSkill().run(report_inp)
                logger.info("Report generated: %s", report.pdf_path)
            except Exception as e:
                logger.warning("Report generation failed: %s", e)

        log_pipeline_end(run_id, "completed")
        return result

    except Exception as e:
        logger.error("Variant discovery pipeline failed: %s", e)
        log_pipeline_end(run_id, "failed")
        raise


# ── Drug Screen Pipeline ─────────────────────────────────────────────────────


def run_drug_screen(args):
    """SMILES → ChEMBL lookup → docking → ranking."""
    from agentiq_labclaw.connectors.chembl import ChEMBLConnector
    from agentiq_labclaw.skills.docking import DockingInput, MolecularDockingSkill

    run_id = log_pipeline_start("drug_screen")
    logger.info("Starting drug screen pipeline (run_id=%s)", run_id)

    try:
        # Step 1: ChEMBL similarity search
        chembl = ChEMBLConnector()
        similar = chembl.search_compound(args.smiles, similarity=args.similarity or 70)
        logger.info("ChEMBL found %d similar compounds", len(similar))
        log_result(run_id, "chembl_similarity", {"query": args.smiles, "hits": len(similar), "compounds": similar})

        # Step 2: Dock each candidate against receptor
        docking_skill = MolecularDockingSkill()
        results = []

        candidates = [args.smiles] + [c.get("smiles", "") for c in similar[:args.max_candidates - 1] if c.get("smiles")]

        for smiles in candidates:
            if not smiles:
                continue
            try:
                dock_inp = DockingInput(
                    ligand_smiles=smiles,
                    receptor_pdb=args.receptor,
                    center_x=args.center_x,
                    center_y=args.center_y,
                    center_z=args.center_z,
                )
                dock_result = docking_skill.run(dock_inp)
                results.append({
                    "smiles": smiles,
                    "affinity": dock_result.binding_affinity_kcal,
                    "pose": dock_result.pose_pdb_path,
                })
                logger.info("Docked %s → %.2f kcal/mol", smiles[:30], dock_result.binding_affinity_kcal)
            except Exception as e:
                logger.warning("Docking failed for %s: %s", smiles[:30], e)

        # Rank by binding affinity (most negative = best)
        results.sort(key=lambda x: x["affinity"])
        log_result(run_id, "docking_screen", {"ranked_hits": results}, novel=bool(results))
        log_pipeline_end(run_id, "completed")

        logger.info("Drug screen complete: %d/%d docked successfully", len(results), len(candidates))
        for i, r in enumerate(results[:5]):
            logger.info("  #%d: %.2f kcal/mol — %s", i + 1, r["affinity"], r["smiles"][:40])

        return results

    except Exception as e:
        logger.error("Drug screen pipeline failed: %s", e)
        log_pipeline_end(run_id, "failed")
        raise


# ── CLI ──────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="OpenCure Labs Pipeline Runner")
    sub = parser.add_subparsers(dest="pipeline", required=True)

    # Neoantigen
    neo = sub.add_parser("neoantigen", help="Neoantigen discovery pipeline")
    neo.add_argument("--vcf", required=True, help="Path to somatic VCF file")
    neo.add_argument("--hla", required=True, help="Comma-separated HLA alleles")
    neo.add_argument("--sample-id", dest="sample_id", help="Sample identifier")
    neo.add_argument("--tumor-type", dest="tumor_type", default="unknown")

    # Variant discovery
    var = sub.add_parser("variant_discovery", help="Variant pathogenicity pipeline")
    var.add_argument("--variant", required=True, help="Variant ID (e.g., chr17:7674220:C>T)")
    var.add_argument("--gene", required=True, help="Gene symbol")
    var.add_argument("--transcript", help="Transcript ID")

    # Drug screen
    drug = sub.add_parser("drug_screen", help="Drug screening pipeline")
    drug.add_argument("--smiles", required=True, help="Query SMILES string")
    drug.add_argument("--receptor", required=True, help="Receptor PDB file")
    drug.add_argument("--center-x", dest="center_x", type=float, default=0.0)
    drug.add_argument("--center-y", dest="center_y", type=float, default=0.0)
    drug.add_argument("--center-z", dest="center_z", type=float, default=0.0)
    drug.add_argument("--similarity", type=int, default=70, help="ChEMBL similarity threshold")
    drug.add_argument("--max-candidates", dest="max_candidates", type=int, default=10)

    args = parser.parse_args()

    if args.pipeline == "neoantigen":
        run_neoantigen(args)
    elif args.pipeline == "variant_discovery":
        run_variant_discovery(args)
    elif args.pipeline == "drug_screen":
        run_drug_screen(args)


if __name__ == "__main__":
    main()
