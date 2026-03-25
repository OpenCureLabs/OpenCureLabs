#!/usr/bin/env python3
"""
D1 central task queue client — claim and complete tasks via the Cloudflare Worker API.

Used by run_research.sh to pull tasks from the shared D1 queue instead of
(or in addition to) the hardcoded local task list.  This ensures the local lab
and external contributors share one unified work queue with no duplicate effort.

Usage:
    # Claim next available task — prints JSON to stdout
    python3 scripts/d1_tasks.py claim [--count 1] [--skill neoantigen_prediction]

    # Mark a task as completed
    python3 scripts/d1_tasks.py complete <task_id> [--result-id <id>]

    # Show queue stats
    python3 scripts/d1_tasks.py stats

Exit codes:
    0  — success (task claimed / completed / stats printed)
    1  — no tasks available or API error
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

API_URL = os.environ.get("OPENCURE_API_URL", "https://ingest.opencurelabs.ai")
CONTRIBUTOR_ID = os.environ.get("OPENCURE_CONTRIBUTOR_ID", "local-lab")
TIMEOUT = 15

# ── Skill-to-coordinator task description mapping ────────────────────────────
# Converts a D1 task (skill + parameters) into a natural-language description
# that the NemoClaw coordinator can route to the correct LabClaw skill.

_SKILL_TEMPLATES = {
    "neoantigen_prediction": (
        "Predict neoantigens from somatic variants. "
        "Sample: {sample_id}, tumor type: {tumor_type}, "
        "HLA alleles: {hla_alleles}, species: {species}. "
        "VCF path: {vcf_path}."
    ),
    "structure_prediction": (
        "Predict protein structure for {protein_id} using {method}."
    ),
    "qsar": (
        "Train a QSAR {model_type} model on {dataset_path} "
        "predicting {target_column} from SMILES column {smiles_column}."
    ),
    "molecular_docking": (
        "Run molecular docking ({method}): dock ligand {ligand_smiles} "
        "against receptor {receptor_pdb}. "
        "Box center: ({center_x}, {center_y}, {center_z}), size: {box_size}."
    ),
    "variant_pathogenicity": (
        "Assess variant pathogenicity for {gene} variant {variant_id}. "
        "Species: {species}."
    ),
    "sequencing_qc": (
        "Run sequencing quality control on sample {sample_id}."
    ),
}


def _task_to_nat_input(skill: str, input_data: dict) -> str:
    """Convert a D1 task into a coordinator-compatible task description."""
    template = _SKILL_TEMPLATES.get(skill)
    if template:
        try:
            # Format with available fields, leave missing as {key}
            return template.format_map(_SafeDict(input_data))
        except (KeyError, ValueError, IndexError):
            pass
    # Fallback: dump the raw task
    return f"Run {skill} with parameters: {json.dumps(input_data)}"


class _SafeDict(dict):
    """Dict that returns '{key}' for missing keys in str.format_map()."""
    def __missing__(self, key):
        return f"{{{key}}}"


def claim(count: int = 1, skill: str | None = None) -> list[dict]:
    """Claim tasks from D1. Returns list of task dicts with added 'nat_input' field."""
    params = f"count={count}&contributor_id={CONTRIBUTOR_ID}"
    if skill:
        params += f"&skill={skill}"

    url = f"{API_URL}/tasks/claim?{params}"
    req = urllib.request.Request(url, method="GET")  # noqa: S310
    req.add_header("Accept", "application/json")
    req.add_header("User-Agent", "opencure-local-lab/1.0")

    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:  # noqa: S310  # nosec B310
            data = json.loads(resp.read().decode())
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        print(f"D1 claim failed: {e}", file=sys.stderr)
        return []

    tasks = data.get("tasks", [])
    for t in tasks:
        t["nat_input"] = _task_to_nat_input(t["skill"], t.get("input_data", {}))
    return tasks


def complete(task_id: str, result_id: str = "") -> bool:
    """Mark a D1 task as completed. Returns True on success."""
    url = f"{API_URL}/tasks/{task_id}/complete"
    body = json.dumps({"result_id": result_id}).encode()
    req = urllib.request.Request(  # noqa: S310
        url, data=body, method="POST",
        headers={
            "Content-Type": "application/json",
            "User-Agent": "opencure-local-lab/1.0",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:  # noqa: S310  # nosec B310
            data = json.loads(resp.read().decode())
            return data.get("ok", False)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        print(f"D1 complete failed for {task_id}: {e}", file=sys.stderr)
        return False


def stats() -> dict:
    """Fetch queue stats from D1."""
    url = f"{API_URL}/tasks/stats"
    req = urllib.request.Request(url, method="GET")  # noqa: S310
    req.add_header("Accept", "application/json")
    req.add_header("User-Agent", "opencure-local-lab/1.0")

    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:  # noqa: S310  # nosec B310
            return json.loads(resp.read().decode())
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        print(f"D1 stats failed: {e}", file=sys.stderr)
        return {}


# ── CLI entry point ──────────────────────────────────────────────────────────

def main():
    import argparse

    parser = argparse.ArgumentParser(description="D1 central task queue client")
    sub = parser.add_subparsers(dest="command", required=True)

    p_claim = sub.add_parser("claim", help="Claim tasks from D1")
    p_claim.add_argument("--count", type=int, default=1)
    p_claim.add_argument("--skill", help="Filter by skill name")

    p_complete = sub.add_parser("complete", help="Mark task completed")
    p_complete.add_argument("task_id")
    p_complete.add_argument("--result-id", default="")

    sub.add_parser("stats", help="Show queue stats")

    args = parser.parse_args()

    if args.command == "claim":
        tasks = claim(count=args.count, skill=args.skill)
        if not tasks:
            print("No tasks available", file=sys.stderr)
            sys.exit(1)
        print(json.dumps(tasks, indent=2))

    elif args.command == "complete":
        ok = complete(args.task_id, result_id=args.result_id)
        if ok:
            print(f"Task {args.task_id} marked completed")
        else:
            print(f"Failed to complete task {args.task_id}", file=sys.stderr)
            sys.exit(1)

    elif args.command == "stats":
        s = stats()
        if not s:
            sys.exit(1)
        print(json.dumps(s, indent=2))


if __name__ == "__main__":
    main()
