"""OpenCure Labs — End-to-End Coordinator Eval Mode

Systematic testing of the full task → skill → review → publish flow.
Runs predefined benchmark tasks with known expected outcomes and
validates results against ground truth.

Usage:
    python pipelines/eval_mode.py                    # Run all benchmarks
    python pipelines/eval_mode.py --suite neoantigen  # Run specific suite
    python pipelines/eval_mode.py --verbose           # Detailed output
"""

import argparse
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "packages", "agentiq_labclaw"))

logger = logging.getLogger("opencurelabs.eval")
logging.basicConfig(level=logging.INFO, format="%(name)s | %(levelname)s | %(message)s")


@dataclass
class EvalCase:
    """A single benchmark test case."""
    name: str
    suite: str
    skill: str
    input_data: dict
    validators: list  # list of (field_path, check_fn_name, expected)
    description: str = ""


@dataclass
class EvalResult:
    """Result of running a single eval case."""
    case_name: str
    suite: str
    passed: bool
    duration_s: float
    checks: list[dict] = field(default_factory=list)
    error: str | None = None


# ── Benchmark Test Cases ─────────────────────────────────────────────────────

EVAL_CASES = [
    # Neoantigen suite
    EvalCase(
        name="neoantigen_tp53_basic",
        suite="neoantigen",
        skill="neoantigen",
        description="TP53/KRAS neoantigen prediction with common HLA alleles",
        input_data={
            "sample_id": "EVAL_TP53",
            "vcf_path": os.path.join(os.path.dirname(__file__), "..", "tests", "data", "synthetic_somatic.vcf"),
            "hla_alleles": ["HLA-A*02:01", "HLA-A*03:01", "HLA-B*07:02"],
            "tumor_type": "NSCLC",
        },
        validators=[
            ("sample_id", "equals", "EVAL_TP53"),
            ("candidates", "is_list", None),
            ("confidence_score", "in_range", (0.0, 1.0)),
            ("novel", "is_bool", None),
        ],
    ),

    # Variant pathogenicity suite
    EvalCase(
        name="variant_tp53_pathogenic",
        suite="variant",
        skill="variant_pathogenicity",
        description="Known pathogenic TP53 variant should classify correctly",
        input_data={
            "variant_id": "chr17:7674220:C>T",
            "gene": "TP53",
        },
        validators=[
            ("variant_id", "equals", "chr17:7674220:C>T"),
            ("gene", "equals", "TP53"),
            ("classification", "in_set", ("pathogenic", "likely_pathogenic")),
            ("pathogenicity_score", "in_range", (0.5, 1.0)),
        ],
    ),

    # Structure prediction suite
    EvalCase(
        name="structure_esmfold_short",
        suite="structure",
        skill="structure_prediction",
        description="Short peptide structure prediction should return valid PDB",
        input_data={
            "protein_id": "EVAL_SHORT",
            "sequence": "MKTIIALSYIFCLVFADYKDDDDK",
            "method": "esmfold",
        },
        validators=[
            ("protein_id", "equals", "EVAL_SHORT"),
            ("method_used", "equals", "esmfold"),
            ("confidence_score", "in_range", (0.0, 1.0)),
            ("pdb_path", "endswith", ".pdb"),
        ],
    ),

    # QSAR suite
    EvalCase(
        name="qsar_descriptors",
        suite="qsar",
        skill="qsar_descriptors",
        description="RDKit descriptor computation for known molecules",
        input_data={
            "smiles_list": ["CCO", "CC(=O)O", "c1ccccc1"],
        },
        validators=[
            ("descriptors_computed", "equals", True),
        ],
    ),

    # Report generation suite
    EvalCase(
        name="report_basic_pdf",
        suite="report",
        skill="report_generator",
        description="Basic PDF report generation with sections and table",
        input_data={
            "title": "Eval Test Report",
            "pipeline_run_id": 0,
            "sections": [
                {"heading": "Summary", "content": "Eval test content."},
                {"heading": "Data", "content": "Results", "table": [["Col1", "Col2"], ["A", "B"]]},
            ],
            "output_dir": "/tmp/opencurelabs_eval/",
        },
        validators=[
            ("pdf_path", "endswith", ".pdf"),
            ("page_count", "gte", 1),
        ],
    ),
]


# ── Validator Functions ──────────────────────────────────────────────────────


def _validate(result_dict: dict, field_path: str, check: str, expected) -> dict:
    """Run a single validation check on a result."""
    value = result_dict.get(field_path)
    passed = False
    detail = ""

    if check == "equals":
        passed = value == expected
        detail = f"got {value!r}, expected {expected!r}"
    elif check == "is_list":
        passed = isinstance(value, list)
        detail = f"type={type(value).__name__}"
    elif check == "is_bool":
        passed = isinstance(value, bool)
        detail = f"type={type(value).__name__}"
    elif check == "in_range":
        lo, hi = expected
        passed = isinstance(value, (int, float)) and lo <= value <= hi
        detail = f"value={value}, range=[{lo}, {hi}]"
    elif check == "in_set":
        passed = value in expected
        detail = f"value={value!r}, allowed={expected}"
    elif check == "endswith":
        passed = isinstance(value, str) and value.endswith(expected)
        detail = f"value={value!r}"
    elif check == "gte":
        passed = isinstance(value, (int, float)) and value >= expected
        detail = f"value={value}, min={expected}"

    return {
        "field": field_path,
        "check": check,
        "passed": passed,
        "detail": detail,
    }


# ── Skill Runner ─────────────────────────────────────────────────────────────


def _run_skill(skill_name: str, input_data: dict):
    """Instantiate and run a skill by name."""
    if skill_name == "neoantigen":
        from agentiq_labclaw.skills.neoantigen import NeoantigenInput, NeoantigenSkill
        return NeoantigenSkill().run(NeoantigenInput(**input_data))

    if skill_name == "variant_pathogenicity":
        from agentiq_labclaw.skills.variant_pathogenicity import VariantInput, VariantPathogenicitySkill
        return VariantPathogenicitySkill().run(VariantInput(**input_data))

    if skill_name == "structure_prediction":
        from agentiq_labclaw.skills.structure import StructureInput, StructurePredictionSkill
        return StructurePredictionSkill().run(StructureInput(**input_data))

    if skill_name == "report_generator":
        from agentiq_labclaw.skills.report_generator import ReportGeneratorSkill, ReportInput
        return ReportGeneratorSkill().run(ReportInput(**input_data))

    if skill_name == "qsar_descriptors":
        from agentiq_labclaw.skills.qsar import _compute_descriptors
        all_ok = all(_compute_descriptors(s) is not None for s in input_data["smiles_list"])
        # Return a simple dict for descriptor checks
        return type("Result", (), {"model_dump": lambda self: {"descriptors_computed": all_ok}})()

    raise ValueError(f"Unknown skill: {skill_name}")


# ── Eval Runner ──────────────────────────────────────────────────────────────


def run_eval(cases: list[EvalCase], verbose: bool = False) -> list[EvalResult]:
    """Run eval cases and return results."""
    results = []

    for case in cases:
        logger.info("Running eval: %s — %s", case.name, case.description)
        t0 = time.time()

        try:
            output = _run_skill(case.skill, case.input_data)
            result_dict = output.model_dump() if hasattr(output, "model_dump") else vars(output)
            duration = time.time() - t0

            checks = []
            for field_path, check_fn, expected in case.validators:
                check_result = _validate(result_dict, field_path, check_fn, expected)
                checks.append(check_result)

            all_passed = all(c["passed"] for c in checks)

            if verbose:
                for c in checks:
                    status = "PASS" if c["passed"] else "FAIL"
                    logger.info("  [%s] %s.%s: %s", status, c["field"], c["check"], c["detail"])

            results.append(EvalResult(
                case_name=case.name,
                suite=case.suite,
                passed=all_passed,
                duration_s=round(duration, 3),
                checks=checks,
            ))

        except Exception as e:
            duration = time.time() - t0
            logger.error("  ERROR: %s", e)
            results.append(EvalResult(
                case_name=case.name,
                suite=case.suite,
                passed=False,
                duration_s=round(duration, 3),
                error=str(e),
            ))

    return results


def print_summary(results: list[EvalResult]):
    """Print eval summary table."""
    total = len(results)
    passed = sum(1 for r in results if r.passed)
    failed = total - passed

    print(f"\n{'=' * 60}")
    print("  OpenCure Labs Eval Summary")
    print(f"{'=' * 60}")
    print(f"  Total: {total}  |  Passed: {passed}  |  Failed: {failed}")
    print(f"{'─' * 60}")

    for r in results:
        status = "PASS" if r.passed else "FAIL"
        icon = "✅" if r.passed else "❌"
        err = f" — {r.error[:50]}" if r.error else ""
        print(f"  {icon} [{status}] {r.case_name:<35} {r.duration_s:>6.3f}s{err}")

        if not r.passed and r.checks:
            for c in r.checks:
                if not c["passed"]:
                    print(f"       ↳ {c['field']}.{c['check']}: {c['detail']}")

    print(f"{'=' * 60}")
    accuracy = (passed / total * 100) if total else 0
    print(f"  Accuracy: {accuracy:.1f}%")
    total_time = sum(r.duration_s for r in results)
    print(f"  Total time: {total_time:.2f}s")
    print(f"{'=' * 60}\n")

    # Write JSON report
    report_path = os.path.join(os.path.dirname(__file__), "..", "reports", "eval_results.json")
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, "w") as f:
        json.dump(
            {
                "total": total,
                "passed": passed,
                "failed": failed,
                "accuracy_pct": accuracy,
                "total_time_s": total_time,
                "results": [
                    {
                        "name": r.case_name,
                        "suite": r.suite,
                        "passed": r.passed,
                        "duration_s": r.duration_s,
                        "checks": r.checks,
                        "error": r.error,
                    }
                    for r in results
                ],
            },
            f,
            indent=2,
        )
    logger.info("Eval report saved to %s", report_path)


def main():
    parser = argparse.ArgumentParser(description="OpenCure Labs E2E Eval Mode")
    parser.add_argument("--suite", help="Run only a specific test suite (neoantigen, variant, structure, qsar, report)")
    parser.add_argument("--verbose", action="store_true", help="Show detailed check results")
    parser.add_argument("--case", help="Run a specific test case by name")
    args = parser.parse_args()

    cases = EVAL_CASES
    if args.suite:
        cases = [c for c in cases if c.suite == args.suite]
    if args.case:
        cases = [c for c in cases if c.name == args.case]

    if not cases:
        logger.error("No matching eval cases found")
        sys.exit(1)

    logger.info("Running %d eval case(s)...", len(cases))
    results = run_eval(cases, verbose=args.verbose)
    print_summary(results)

    # Exit with non-zero if any failed
    if any(not r.passed for r in results):
        sys.exit(1)


if __name__ == "__main__":
    main()
