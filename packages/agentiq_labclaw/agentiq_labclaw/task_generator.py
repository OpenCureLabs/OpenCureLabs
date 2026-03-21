"""
Parameterized task generator — expands base research tasks into 100+ batch variants.

Each variant combines a LabClaw skill with concrete input parameters drawn from
curated gene lists, compound libraries, and clinical datasets.  The generator
can be driven from a YAML config (config/research_tasks.yaml) or fall back to
built-in defaults.

Usage:
    from agentiq_labclaw.task_generator import generate_batch
    tasks = generate_batch(count=100)            # default mix
    tasks = generate_batch(count=50, domain="cancer")   # single domain
    tasks = generate_batch(config_path="config/research_tasks.yaml")
"""

from __future__ import annotations

import itertools
import logging
import random
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger("labclaw.task_generator")

# ── BatchTask dataclass ──────────────────────────────────────────────────────

@dataclass
class BatchTask:
    """A single unit of work to dispatch to the Vast.ai pool."""
    skill_name: str            # maps to _SKILL_MODULES key in skills/__init__.py
    input_data: dict[str, Any]
    domain: str                # "cancer" | "drug_discovery" | "rare_disease"
    label: str = ""            # human-readable description
    priority: int = 5          # 1 (highest) – 10 (lowest)
    estimated_gpu_min: int = 5 # rough GPU time estimate

    def to_dict(self) -> dict:
        return asdict(self)


# ── Curated parameter banks ──────────────────────────────────────────────────
# Real genes, variants, targets, and compounds from public databases.

CANCER_GENES = [
    ("TP53",  "chr17:7674220:C>T",  "R248W"),
    ("BRCA1", "chr17:43094464:G>A", "C61G"),
    ("EGFR",  "chr7:55259515:T>G",  "L858R"),
    ("KRAS",  "chr12:25245350:C>A", "G12V"),
    ("PIK3CA","chr3:179234297:A>G", "H1047R"),
    ("BRAF",  "chr7:140753336:A>T", "V600E"),
    ("PTEN",  "chr10:87933147:C>T", "R130Q"),
    ("ALK",   "chr2:29415640:C>A",  "F1174L"),
    ("RET",   "chr10:43609944:C>T", "M918T"),
    ("MET",   "chr7:116411990:G>A", "T1010I"),
    ("HER2",  "chr17:39724775:A>G", "S310F"),
    ("IDH1",  "chr2:208248388:C>T", "R132H"),
    ("FGFR3", "chr4:1803568:G>C",   "S249C"),
    ("CDH1",  "chr16:68835675:G>A", "R732Q"),
    ("APC",   "chr5:112175770:C>T", "R1450X"),
]

TUMOR_TYPES = [
    "NSCLC", "breast", "colorectal", "melanoma", "glioblastoma",
    "pancreatic", "ovarian", "prostate", "hepatocellular", "renal",
]

HLA_PANELS = [
    ["HLA-A*02:01", "HLA-B*07:02", "HLA-C*07:02"],
    ["HLA-A*01:01", "HLA-B*08:01", "HLA-C*07:01"],
    ["HLA-A*03:01", "HLA-B*44:03", "HLA-C*04:01"],
    ["HLA-A*24:02", "HLA-B*35:01", "HLA-C*04:01"],
    ["HLA-A*11:01", "HLA-B*15:01", "HLA-C*03:04"],
]

# Drug discovery — real target proteins and reference ligands
DRUG_TARGETS = [
    {"protein_id": "EGFR",    "pdb": "1M17", "seq_len": 330,  "ligand": "erlotinib",  "smiles": "C=Cc1cccc(Nc2ncnc3cc(OCCOC)c(OCCOC)cc23)c1"},
    {"protein_id": "ABL1",    "pdb": "1IEP", "seq_len": 290,  "ligand": "imatinib",   "smiles": "Cc1ccc(NC(=O)c2ccc(CN3CCN(C)CC3)cc2)cc1Nc1nccc(-c2cccnc2)n1"},
    {"protein_id": "BRAF",    "pdb": "1UWH", "seq_len": 767,  "ligand": "vemurafenib","smiles": "CCCS(=O)(=O)Nc1ccc(-c2c[nH]c3c(F)cc(-c4cc(F)c(Cl)cc4F)cc23)cc1F"},
    {"protein_id": "CDK4",    "pdb": "2W96", "seq_len": 303,  "ligand": "palbociclib","smiles": "CC(=O)c1c(C)c2cnc(Nc3ccc(N4CCNCC4)cn3)nc2n(C2CCCC2)c1=O"},
    {"protein_id": "ALK",     "pdb": "2XP2", "seq_len": 1620, "ligand": "crizotinib", "smiles": "CC(Oc1cc(-c2cnn(C3CCNCC3)c2)cnc1N)c1c(Cl)ccc(F)c1Cl"},
    {"protein_id": "JAK2",    "pdb": "3FUP", "seq_len": 1132, "ligand": "ruxolitinib","smiles": "N#Cc1cc(-c2ccnc3[nH]ccc23)cn1CC1CCC1"},
    {"protein_id": "BTK",     "pdb": "3GEN", "seq_len": 659,  "ligand": "ibrutinib",  "smiles": "C=CC(=O)Nc1cccc(-n2c(=O)c3[nH]c4ccccc4c3c3cc(N4CCOCC4)ccc32)c1"},
    {"protein_id": "PI3Kα",   "pdb": "4JPS", "seq_len": 1068, "ligand": "alpelisib",  "smiles": "CC1(C)Cc2cnc(Nc3cc(F)c(S(=O)(=O)C4CC4)c(F)c3)nc2CO1"},
    {"protein_id": "PARP1",   "pdb": "5DS3", "seq_len": 1014, "ligand": "olaparib",   "smiles": "O=C(c1cc2ccccc2c(=O)[nH]1)N1CCN(C(=O)c2cc3ccccc3[nH]c2=O)CC1"},
    {"protein_id": "PD-L1",   "pdb": "5J89", "seq_len": 290,  "ligand": "BMS-202",    "smiles": "CCOc1cc(OC)cc(/C=C/c2cc[nH+]c(NC3CCCCC3)c2)c1"},
]

CHEMBL_DATASETS = [
    {"name": "EGFR_IC50",     "target": "CHEMBL203",  "target_col": "pIC50"},
    {"name": "JAK2_IC50",     "target": "CHEMBL2971",  "target_col": "pIC50"},
    {"name": "BRAF_EC50",     "target": "CHEMBL5145",  "target_col": "pEC50"},
    {"name": "CDK4_IC50",     "target": "CHEMBL3116",  "target_col": "pIC50"},
    {"name": "ALK_IC50",      "target": "CHEMBL4247",  "target_col": "pIC50"},
    {"name": "BTK_IC50",      "target": "CHEMBL5251",  "target_col": "pIC50"},
    {"name": "PI3K_IC50",     "target": "CHEMBL4005",  "target_col": "pIC50"},
    {"name": "PARP_IC50",     "target": "CHEMBL3105",  "target_col": "pIC50"},
    {"name": "PD1_binding",   "target": "CHEMBL4630",  "target_col": "pIC50"},
    {"name": "mTOR_IC50",     "target": "CHEMBL2842",  "target_col": "pIC50"},
]

# Rare disease — real pathogenic variants from ClinVar
RARE_DISEASE_VARIANTS = [
    {"variant_id": "chr7:117559590:A>G",  "gene": "CFTR",     "hgvs": "p.Gly551Asp", "disease": "Cystic fibrosis"},
    {"variant_id": "chr11:5248232:T>A",   "gene": "HBB",      "hgvs": "p.Glu6Val",   "disease": "Sickle cell disease"},
    {"variant_id": "chr13:32911463:T>G",  "gene": "BRCA2",    "hgvs": "p.Tyr1894Ter","disease": "Hereditary breast cancer"},
    {"variant_id": "chr4:3076604:C>T",    "gene": "HTT",      "hgvs": None,           "disease": "Huntington disease"},
    {"variant_id": "chr17:48275363:C>T",  "gene": "COL1A1",   "hgvs": "p.Gly382Ser", "disease": "Osteogenesis imperfecta"},
    {"variant_id": "chr1:11856378:G>A",   "gene": "MTHFR",    "hgvs": "p.Ala222Val", "disease": "Homocystinuria"},
    {"variant_id": "chr12:40740686:G>A",  "gene": "LRRK2",    "hgvs": "p.Gly2019Ser","disease": "Parkinson disease"},
    {"variant_id": "chr15:89859516:C>T",  "gene": "POLG",     "hgvs": "p.Ala467Thr", "disease": "Mitochondrial DNA depletion"},
    {"variant_id": "chr6:161006172:G>A",  "gene": "PARK2",    "hgvs": "p.Arg275Trp", "disease": "Juvenile Parkinson"},
    {"variant_id": "chr1:155235843:G>T",  "gene": "GBA",      "hgvs": "p.Asn370Ser", "disease": "Gaucher disease"},
    {"variant_id": "chr5:149433596:C>T",  "gene": "CSF1R",    "hgvs": "p.Arg777Gln", "disease": "Leukoencephalopathy"},
    {"variant_id": "chr2:166850645:C>T",  "gene": "SCN1A",    "hgvs": "p.Arg1648Cys","disease": "Dravet syndrome"},
    {"variant_id": "chr22:42526694:G>A",  "gene": "CYP2D6",   "hgvs": "p.Pro34Ser",  "disease": "Poor drug metabolism"},
    {"variant_id": "chr3:37089131:G>A",   "gene": "MLH1",     "hgvs": "p.Arg226Ter", "disease": "Lynch syndrome"},
    {"variant_id": "chr11:108202608:C>T", "gene": "ATM",      "hgvs": "p.Arg3008Cys","disease": "Ataxia-telangiectasia"},
]


# ── Task generators per skill ───────────────────────────────────────────────

def _neoantigen_tasks(count: int) -> list[BatchTask]:
    """Generate neoantigen prediction tasks across genes × tumor types × HLA panels."""
    combos = list(itertools.product(CANCER_GENES, TUMOR_TYPES, HLA_PANELS))
    random.shuffle(combos)
    tasks = []
    for (gene, variant_id, _mutation), tumor, hla in combos[:count]:
        tasks.append(BatchTask(
            skill_name="neoantigen_prediction",
            input_data={
                "sample_id": f"{gene}_{tumor}_batch",
                "vcf_path": f"data/tcga/{tumor.lower()}/{gene.lower()}_somatic.vcf",
                "hla_alleles": hla,
                "tumor_type": tumor,
            },
            domain="cancer",
            label=f"Neoantigen: {gene} in {tumor}",
            priority=3,
            estimated_gpu_min=5,
        ))
    return tasks


def _structure_tasks(count: int, domain: str = "cancer") -> list[BatchTask]:
    """Generate structure prediction tasks for cancer or drug target proteins."""
    # Use placeholder sequences (real runs will fetch from UniProt)
    sources = CANCER_GENES if domain == "cancer" else DRUG_TARGETS
    tasks = []
    for i, src in enumerate(itertools.cycle(sources)):
        if i >= count:
            break
        if domain == "cancer":
            pid = src[0]  # gene name
            label = f"Structure: {pid} (cancer)"
        else:
            pid = src["protein_id"]
            label = f"Structure: {pid} (drug target)"
        tasks.append(BatchTask(
            skill_name="structure_prediction",
            input_data={
                "protein_id": pid,
                "sequence": "PLACEHOLDER_FETCH_FROM_UNIPROT",
                "method": "esmfold",
            },
            domain=domain,
            label=label,
            priority=4,
            estimated_gpu_min=10,
        ))
    return tasks


def _qsar_tasks(count: int) -> list[BatchTask]:
    """Generate QSAR training tasks across ChEMBL datasets × model types."""
    model_types = ["random_forest", "xgboost"]
    combos = list(itertools.product(CHEMBL_DATASETS, model_types))
    random.shuffle(combos)
    tasks = []
    for ds, model in combos[:count]:
        tasks.append(BatchTask(
            skill_name="qsar",
            input_data={
                "dataset_path": f"data/chembl/{ds['name']}.csv",
                "target_column": ds["target_col"],
                "smiles_column": "smiles",
                "model_type": model,
                "mode": "train",
            },
            domain="drug_discovery",
            label=f"QSAR: {ds['name']} ({model})",
            priority=5,
            estimated_gpu_min=8,
        ))
    return tasks


def _docking_tasks(count: int) -> list[BatchTask]:
    """Generate molecular docking tasks across targets × methods."""
    methods = ["vina", "gnina"]
    combos = list(itertools.product(DRUG_TARGETS, methods))
    random.shuffle(combos)
    tasks = []
    for target, method in combos[:count]:
        tasks.append(BatchTask(
            skill_name="molecular_docking",
            input_data={
                "ligand_smiles": target["smiles"],
                "receptor_pdb": f"data/pdb/{target['pdb']}.pdb",
                "center_x": 0.0,
                "center_y": 0.0,
                "center_z": 0.0,
                "box_size": 25.0,
                "exhaustiveness": 16,
                "method": method,
            },
            domain="drug_discovery",
            label=f"Docking: {target['ligand']} → {target['protein_id']} ({method})",
            priority=4,
            estimated_gpu_min=15,
        ))
    return tasks


def _variant_pathogenicity_tasks(count: int) -> list[BatchTask]:
    """Generate variant pathogenicity scoring tasks from ClinVar variants."""
    variants = list(RARE_DISEASE_VARIANTS)
    random.shuffle(variants)
    tasks = []
    for v in itertools.islice(itertools.cycle(variants), count):
        tasks.append(BatchTask(
            skill_name="variant_pathogenicity",
            input_data={
                "variant_id": v["variant_id"],
                "gene": v["gene"],
                "hgvs": v.get("hgvs"),
            },
            domain="rare_disease",
            label=f"Variant: {v['gene']} ({v['disease']})",
            priority=3,
            estimated_gpu_min=2,
        ))
    return tasks


def _sequencing_qc_tasks(count: int, domain: str = "cancer") -> list[BatchTask]:
    """Generate QC tasks for different sample types."""
    samples = CANCER_GENES if domain == "cancer" else RARE_DISEASE_VARIANTS
    tasks = []
    for i, src in enumerate(itertools.islice(itertools.cycle(samples), count)):
        if domain == "cancer":
            sid = f"{src[0]}_tumor_qc"
        else:
            sid = f"{src['gene']}_rare_qc"
        tasks.append(BatchTask(
            skill_name="sequencing_qc",
            input_data={
                "sample_id": sid,
                "fastq_paths": [f"data/fastq/{sid}_R1.fastq.gz", f"data/fastq/{sid}_R2.fastq.gz"],
                "reference_genome": "hg38",
            },
            domain=domain,
            label=f"QC: {sid}",
            priority=7,
            estimated_gpu_min=3,
        ))
    return tasks


# ── Distribution config ──────────────────────────────────────────────────────

# Default task distribution across skills — roughly mirrors real research priorities
DEFAULT_DISTRIBUTION = {
    "neoantigen_prediction": 0.20,   # 20%
    "structure_cancer":      0.08,   # 8%  (structure for cancer proteins)
    "structure_drug":        0.08,   # 8%  (structure for drug targets)
    "qsar":                  0.15,   # 15%
    "molecular_docking":     0.15,   # 15%
    "variant_pathogenicity": 0.20,   # 20%
    "sequencing_qc_cancer":  0.07,   # 7%
    "sequencing_qc_rare":    0.07,   # 7%
}

_GENERATORS = {
    "neoantigen_prediction": lambda n: _neoantigen_tasks(n),
    "structure_cancer":      lambda n: _structure_tasks(n, "cancer"),
    "structure_drug":        lambda n: _structure_tasks(n, "drug_discovery"),
    "qsar":                  lambda n: _qsar_tasks(n),
    "molecular_docking":     lambda n: _docking_tasks(n),
    "variant_pathogenicity": lambda n: _variant_pathogenicity_tasks(n),
    "sequencing_qc_cancer":  lambda n: _sequencing_qc_tasks(n, "cancer"),
    "sequencing_qc_rare":    lambda n: _sequencing_qc_tasks(n, "rare_disease"),
}

DOMAIN_FILTERS = {
    "cancer":         {"neoantigen_prediction", "structure_cancer", "sequencing_qc_cancer"},
    "drug_discovery": {"structure_drug", "qsar", "molecular_docking"},
    "rare_disease":   {"variant_pathogenicity", "sequencing_qc_rare"},
}


# ── Public API ───────────────────────────────────────────────────────────────

def generate_batch(
    count: int = 100,
    domain: str | None = None,
    config_path: str | None = None,
    seed: int | None = None,
) -> list[BatchTask]:
    """Generate a batch of parameterized research tasks.

    Args:
        count:       Total number of tasks to generate.
        domain:      Filter to a single domain ("cancer", "drug_discovery", "rare_disease").
                     None = all domains.
        config_path: Path to a YAML config with custom task templates.
                     Falls back to built-in defaults if absent.
        seed:        Random seed for reproducibility.

    Returns:
        List of BatchTask objects ready for batch_queue.submit_batch().
    """
    if seed is not None:
        random.seed(seed)

    # Load distribution — from YAML config or built-in defaults
    if config_path and Path(config_path).exists():
        distribution, custom_tasks = _load_yaml_config(config_path)
    else:
        distribution = dict(DEFAULT_DISTRIBUTION)
        custom_tasks = []

    # Filter by domain if requested
    if domain:
        allowed = DOMAIN_FILTERS.get(domain, set())
        distribution = {k: v for k, v in distribution.items() if k in allowed}

    # Normalize weights
    total_weight = sum(distribution.values())
    if total_weight == 0:
        raise ValueError(f"No tasks match domain={domain!r}")

    # Allocate counts per skill type
    tasks: list[BatchTask] = []
    remaining = count - len(custom_tasks)

    for skill_key, weight in distribution.items():
        n = max(1, round(remaining * weight / total_weight))
        gen = _GENERATORS.get(skill_key)
        if gen:
            tasks.extend(gen(n))

    # Add custom tasks from YAML
    tasks.extend(custom_tasks)

    # Trim or pad to exact count
    random.shuffle(tasks)
    tasks = tasks[:count]

    logger.info(
        "Generated %d batch tasks across %d skill types (domain=%s)",
        len(tasks),
        len(set(t.skill_name for t in tasks)),
        domain or "all",
    )
    return tasks


def _load_yaml_config(config_path: str) -> tuple[dict, list[BatchTask]]:
    """Load task distribution and custom tasks from YAML config."""
    with open(config_path) as f:
        cfg = yaml.safe_load(f) or {}

    distribution = cfg.get("distribution", dict(DEFAULT_DISTRIBUTION))
    custom_tasks = []

    for task_def in cfg.get("custom_tasks", []):
        custom_tasks.append(BatchTask(
            skill_name=task_def["skill_name"],
            input_data=task_def.get("input_data", {}),
            domain=task_def.get("domain", "custom"),
            label=task_def.get("label", "Custom task"),
            priority=task_def.get("priority", 5),
            estimated_gpu_min=task_def.get("estimated_gpu_min", 5),
        ))

    return distribution, custom_tasks


# ── CLI entry point ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Generate batch research tasks")
    parser.add_argument("--count", type=int, default=100, help="Number of tasks")
    parser.add_argument("--domain", choices=["cancer", "drug_discovery", "rare_disease"])
    parser.add_argument("--config", help="Path to research_tasks.yaml")
    parser.add_argument("--seed", type=int, help="Random seed")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    batch = generate_batch(
        count=args.count,
        domain=args.domain,
        config_path=args.config,
        seed=args.seed,
    )

    if args.json:
        print(json.dumps([t.to_dict() for t in batch], indent=2, default=str))
    else:
        for i, t in enumerate(batch, 1):
            print(f"[{i:3d}] {t.domain:15s} | {t.skill_name:25s} | {t.label}")
        print(f"\nTotal: {len(batch)} tasks")
