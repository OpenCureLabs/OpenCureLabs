#!/usr/bin/env python3
"""
Convert a high-level research task description into a parameterized instruction.

The RunAll/Genesis mode in run_research.sh sends free-text descriptions like
"Identify somatic mutations from tumor/normal paired sequencing data" to the
coordinator.  The coordinator's tools require specific structured parameters
(vcf_path, sample_id, hla_alleles, etc.) so the LLM cannot invoke them from
free text alone.

This script bridges the gap by mapping task descriptions to skill names and
generating concrete parameters from the curated gene banks in task_generator.py.

Usage:
    python scripts/parameterize_task.py "Predict neoantigens..." --domain cancer
    python scripts/parameterize_task.py "Train a QSAR model..." --domain drug_discovery
"""

from __future__ import annotations

import json
import os
import random
import sys

# Ensure project root is on sys.path so agentiq_labclaw is importable
_project_root = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from agentiq_labclaw.task_generator import generate_batch

# Maps keywords in task descriptions → skill_name in task_generator
# Order matters — first match wins
_KEYWORD_SKILL_MAP = [
    # Cancer
    ("neoantigen",           "neoantigen_prediction"),
    ("somatic mutation",     "neoantigen_prediction"),
    ("tumor mutation",       "neoantigen_prediction"),
    ("immune landscape",     "neoantigen_prediction"),
    ("immune microenviron",  "neoantigen_prediction"),
    # Drug discovery
    ("qsar",                 "qsar"),
    ("drug predictor",       "qsar"),
    ("bioactivity",          "qsar"),
    ("molecular docking",    "molecular_docking"),
    ("virtual screening",    "molecular_docking"),
    ("screen drug",          "molecular_docking"),
    ("drug candidate",       "molecular_docking"),
    ("lead compound",        "molecular_docking"),
    ("optimize a drug",      "molecular_docking"),
    ("optimize lead",        "molecular_docking"),
    # Structure prediction
    ("protein structure",    "structure_prediction"),
    ("protein shape",        "structure_prediction"),
    ("alphafold",            "structure_prediction"),
    ("esmfold",              "structure_prediction"),
    ("3d structure",         "structure_prediction"),
    # Rare disease
    ("variant pathogenicity","variant_pathogenicity"),
    ("variant danger",       "variant_pathogenicity"),
    ("pathogenicity",        "variant_pathogenicity"),
    ("de novo",              "variant_pathogenicity"),
    ("new mutation",         "variant_pathogenicity"),
    ("clinvar",              "variant_pathogenicity"),
    # QC
    ("sequencing qc",        "sequencing_qc"),
    ("quality control",      "sequencing_qc"),
    ("data quality",         "sequencing_qc"),
    ("read quality",         "sequencing_qc"),
]

# Maps skill_name → the coordinator-visible specialist agent that owns it
_SKILL_AGENT_MAP = {
    "neoantigen_prediction": "cancer_agent",
    "structure_prediction":  "cancer_agent",
    "sequencing_qc":         "cancer_agent",
    "qsar":                  "drug_response_agent",
    "molecular_docking":     "drug_response_agent",
    "variant_pathogenicity": "rare_disease_agent",
}


def _detect_skill(description: str) -> str | None:
    """Detect the target skill name from a free-text task description."""
    desc_lower = description.lower()
    for keyword, skill in _KEYWORD_SKILL_MAP:
        if keyword in desc_lower:
            return skill
    return None


def _detect_domain(description: str, species: str = "human") -> str | None:
    """Detect domain from task description and species."""
    if species == "dog":
        return "canine"
    if species == "cat":
        return "feline"
    desc_lower = description.lower()
    if any(k in desc_lower for k in ("cancer", "tumor", "neoantigen", "somatic", "immune")):
        return "cancer"
    if any(k in desc_lower for k in ("drug", "qsar", "docking", "screen", "ligand", "lead")):
        return "drug_discovery"
    if any(k in desc_lower for k in ("rare", "variant", "pathogen", "de novo", "clinvar")):
        return "rare_disease"
    return None


def parameterize(description: str, species: str = "human", data_mode: str | None = None) -> str:
    """Convert a high-level task into a parameterized coordinator instruction."""
    target_skill = _detect_skill(description)
    domain = _detect_domain(description, species)

    # Generate a batch of tasks and pick one matching the target skill
    tasks = generate_batch(
        count=20, domain=domain,
        species=species if species != "human" else None,
        data_mode=data_mode,
    )
    random.shuffle(tasks)

    task = None
    if target_skill:
        for t in tasks:
            if t.skill_name == target_skill:
                task = t
                break

    # Fallback: take any task from the batch
    if task is None and tasks:
        task = tasks[0]

    if task is None:
        # No parameterization possible — return original description
        return description

    # Resolve placeholder sequences before sending to the coordinator LLM.
    # The LLM rejects AUTO_RESOLVE as invalid; the skill's UniProt lookup
    # never fires because the LLM refuses to call the tool.
    if task.input_data.get("sequence") == "AUTO_RESOLVE" and task.input_data.get("protein_id"):
        from agentiq_labclaw.skills.structure import StructurePredictionSkill

        seq, _ = StructurePredictionSkill._fetch_uniprot_sequence(
            task.input_data["protein_id"]
        )
        if seq:
            task.input_data["sequence"] = seq

    params = json.dumps(task.input_data, indent=2)

    # Resolve which specialist agent owns this skill
    agent_name = _SKILL_AGENT_MAP.get(task.skill_name, "cancer_agent")

    # Build a clear, structured instruction that the coordinator can act on
    return (
        f"Use the {agent_name} tool to run the {task.skill_name} analysis with these exact parameters:\n"
        f"{params}\n\n"
        f"Pass the full instruction above as the input_text argument to {agent_name}. "
        f"Do not ask for clarification — run the analysis with the parameters above."
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Convert a free-text research task into a parameterized instruction"
    )
    parser.add_argument("description", help="High-level task description")
    parser.add_argument("--species", default="human", choices=["human", "dog", "cat"])
    parser.add_argument("--data-mode", choices=["public", "mydata"],
                        help="Data source: public databases or local files")
    args = parser.parse_args()

    print(parameterize(args.description, args.species, data_mode=args.data_mode))
