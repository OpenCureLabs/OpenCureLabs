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
from dataclasses import asdict, dataclass
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
    domain: str = ""           # "cancer" | "drug_discovery" | "rare_disease"
    label: str = ""            # human-readable description
    priority: int = 5          # 1 (highest) – 10 (lowest)
    estimated_gpu_min: int = 5 # rough GPU time estimate
    central_task_id: str | None = None  # ID from central queue (contribute mode)

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
    {"protein_id": "PIK3CA",  "pdb": "4JPS", "seq_len": 1068, "ligand": "alpelisib",  "smiles": "CC1(C)Cc2cnc(Nc3cc(F)c(S(=O)(=O)C4CC4)c(F)c3)nc2CO1", "name": "PI3Kα"},
    {"protein_id": "PARP1",   "pdb": "5DS3", "seq_len": 1014, "ligand": "olaparib",   "smiles": "O=C(c1cc2ccccc2c(=O)[nH]1)N1CCN(C(=O)c2cc3ccccc3[nH]c2=O)CC1"},
    {"protein_id": "CD274",   "pdb": "5J89", "seq_len": 290,  "ligand": "BMS-202",    "smiles": "CCOc1cc(OC)cc(/C=C/c2cc[nH+]c(NC3CCCCC3)c2)c1", "name": "PD-L1"},
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

# ---------------------------------------------------------------------------
# Veterinary gene banks (canine + feline)
# Coordinates are approximate CanFam3.1 / felCat9 positions for reference.
# Actual positions are looked up at runtime via pyensembl.
# ---------------------------------------------------------------------------

CANINE_CANCER_GENES = [
    # (gene_symbol, chrom, variant_type, cancer_type)
    ("BRAF",   "chr16", "V595E",  "mast_cell_tumor"),    # V595E most common dog BRAF (equiv human V600E)
    ("KIT",    "chr13", "exon11", "mast_cell_tumor"),    # Internal tandem duplication / point mut
    ("TP53",   "chr5",  "R175H",  "osteosarcoma"),
    ("BRCA1",  "chr17", "various","mammary_tumor"),
    ("BRCA2",  "chr11", "various","mammary_tumor"),
    ("PTEN",   "chr4",  "R130Q",  "hemangiosarcoma"),
    ("MC1R",   "chr5",  "various","melanoma"),
    ("NRAS",   "chr16", "Q61R",   "melanoma"),
    ("PDGFRA", "chr13", "D842V",  "mast_cell_tumor"),
    ("RAS",    "chr7",  "G12V",   "bladder_tumor"),
]

FELINE_CANCER_GENES = [
    ("KIT",    "chrB1", "exon11", "mast_cell_tumor"),
    ("TP53",   "chrE2", "R248W",  "mammary_carcinoma"),
    ("PDGFRA", "chrB3", "D842V",  "mast_cell_tumor"),
    ("NRAS",   "chrF2", "Q61R",   "lymphoma"),
    ("BRCA1",  "chrB1", "various","mammary_tumor"),
    ("MYC",    "chrA3", "various","lymphoma"),
]

CANINE_TUMOR_TYPES = [
    "mast_cell_tumor", "osteosarcoma", "lymphoma",
    "mammary_tumor", "melanoma", "hemangiosarcoma",
    "transitional_cell_carcinoma", "soft_tissue_sarcoma",
]

FELINE_TUMOR_TYPES = [
    "mammary_carcinoma", "mast_cell_tumor", "lymphoma",
    "squamous_cell_carcinoma", "vaccine_site_sarcoma",
]

# Dog Leukocyte Antigen (DLA) Class I allele panels
# Source: IPD-MHC Database + published veterinary immunogenomics
DLA_PANELS = [
    ["DLA-88*501:01", "DLA-88*508:01", "DLA-12*001:01"],
    ["DLA-88*502:01", "DLA-88*503:01", "DLA-64*001:01"],
    ["DLA-88*506:01", "DLA-88*511:01", "DLA-12*002:01"],
    ["DLA-88*508:02", "DLA-88*515:01", "DLA-64*002:01"],
    ["DLA-88*501:01", "DLA-88*516:01", "DLA-12*001:01"],  # Common in Golden Retrievers
]

# Feline Leukocyte Antigen (FLA) Class I allele panels
# FLA is less characterized than DLA — limited published alleles
FLA_PANELS = [
    ["FLA-K*001", "FLA-K*002"],
    ["FLA-1600*001", "FLA-K*001"],
    ["FLA-K*003", "FLA-1600*002"],
]

CANINE_VARIANTS = [
    {"variant_id": "chr16:26835234:A>T",  "gene": "BRAF",   "disease": "Mast cell tumor",  "species": "dog"},
    {"variant_id": "chr13:28001012:G>A",  "gene": "KIT",    "disease": "Mast cell tumor",  "species": "dog"},
    {"variant_id": "chr5:53824190:G>A",   "gene": "TP53",   "disease": "Osteosarcoma",     "species": "dog"},
    {"variant_id": "chr4:50821099:C>T",   "gene": "PTEN",   "disease": "Hemangiosarcoma",  "species": "dog"},
    {"variant_id": "chr5:33924088:G>A",   "gene": "MC1R",   "disease": "Melanoma",         "species": "dog"},
    {"variant_id": "chr16:35102234:A>G",  "gene": "NRAS",   "disease": "Melanoma",         "species": "dog"},
    {"variant_id": "chr13:27990100:G>T",  "gene": "PDGFRA", "disease": "Mast cell tumor",  "species": "dog"},
    {"variant_id": "chr17:4523112:C>T",   "gene": "BRCA1",  "disease": "Mammary tumor",    "species": "dog"},
    {"variant_id": "chr11:9941812:G>A",   "gene": "BRCA2",  "disease": "Mammary tumor",    "species": "dog"},
]

FELINE_VARIANTS = [
    {"variant_id": "chrB1:41200123:G>T",  "gene": "KIT",    "disease": "Mast cell tumor",      "species": "cat"},
    {"variant_id": "chrE2:29823456:G>A",  "gene": "TP53",   "disease": "Mammary carcinoma",    "species": "cat"},
    {"variant_id": "chrB3:15023890:A>G",  "gene": "PDGFRA", "disease": "Mast cell tumor",      "species": "cat"},
    {"variant_id": "chrF2:12340500:C>T",  "gene": "NRAS",   "disease": "Lymphoma",             "species": "cat"},
    {"variant_id": "chrB1:44500321:C>T",  "gene": "BRCA1",  "disease": "Mammary tumor",        "species": "cat"},
]


# ── Task generators per skill ───────────────────────────────────────────────

def _neoantigen_tasks(count: int, species: str = "human") -> list[BatchTask]:
    """Generate neoantigen prediction tasks across genes × tumor types × MHC panels."""
    if species == "dog":
        genes = [(
                g[0],
                f"{g[1]}:{random.randint(1000000, 50000000)}:A>T",
                g[2],
            ) for g in CANINE_CANCER_GENES]
        tumor_types = CANINE_TUMOR_TYPES
        hla_panels = DLA_PANELS
        ref_genome = "CanFam3.1"
    elif species == "cat":
        genes = [(
                g[0],
                f"{g[1]}:{random.randint(1000000, 50000000)}:C>T",
                g[2],
            ) for g in FELINE_CANCER_GENES]
        tumor_types = FELINE_TUMOR_TYPES
        hla_panels = FLA_PANELS
        ref_genome = "felCat9"
    else:
        genes = CANCER_GENES
        tumor_types = TUMOR_TYPES
        hla_panels = HLA_PANELS
        ref_genome = "GRCh38"

    combos = list(itertools.product(genes, tumor_types, hla_panels))
    random.shuffle(combos)
    tasks = []
    for (gene, variant_id, _mutation), tumor, mhc in combos[:count]:
        tasks.append(BatchTask(
            skill_name="neoantigen_prediction",
            input_data={
                "sample_id": f"{gene}_{tumor}_{species}_batch",
                "vcf_path": f"data/{species}/{tumor.lower()}/{gene.lower()}_somatic.vcf",
                "hla_alleles": mhc,
                "tumor_type": tumor,
                "species": species,
            },
            domain="cancer",
            label=f"Neoantigen [{species}]: {gene} in {tumor}",
            priority=3,
            estimated_gpu_min=5,
        ))
    return tasks


def _structure_tasks(count: int, domain: str = "cancer") -> list[BatchTask]:
    """Generate structure prediction tasks for cancer or drug target proteins."""
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
            name = src.get("name", pid)
            label = f"Structure: {name} (drug target)"
        tasks.append(BatchTask(
            skill_name="structure_prediction",
            input_data={
                "protein_id": pid,
                "sequence": "AUTO_RESOLVE",
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
                "dataset_path": f"data/chembl/{ds['target']}.csv",
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
            label=f"Docking: {target['ligand']} → {target.get('name', target['protein_id'])} ({method})",
            priority=4,
            estimated_gpu_min=15,
        ))
    return tasks


def _variant_pathogenicity_tasks(count: int, species: str = "human") -> list[BatchTask]:
    """Generate variant pathogenicity scoring tasks for the given species."""
    if species == "dog":
        variants = list(CANINE_VARIANTS)
    elif species == "cat":
        variants = list(FELINE_VARIANTS)
    else:
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
                "species": v.get("species", "human"),
            },
            domain="rare_disease" if species == "human" else "cancer",
            label=f"Variant [{species}]: {v['gene']} ({v['disease']})",
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
    # Veterinary (only selected when domain=canine or domain=feline)
    "neoantigen_dog":        0.40,   # 40% of canine batch
    "variant_dog":           0.40,   # 40% of canine batch
    "neoantigen_cat":        0.40,   # 40% of feline batch
    "variant_cat":           0.40,   # 40% of feline batch
}

_GENERATORS = {
    "neoantigen_prediction": lambda n: _neoantigen_tasks(n, "human"),
    "neoantigen_dog":        lambda n: _neoantigen_tasks(n, "dog"),
    "neoantigen_cat":        lambda n: _neoantigen_tasks(n, "cat"),
    "structure_cancer":      lambda n: _structure_tasks(n, "cancer"),
    "structure_drug":        lambda n: _structure_tasks(n, "drug_discovery"),
    "qsar":                  lambda n: _qsar_tasks(n),
    "molecular_docking":     lambda n: _docking_tasks(n),
    "variant_pathogenicity": lambda n: _variant_pathogenicity_tasks(n, "human"),
    "variant_dog":           lambda n: _variant_pathogenicity_tasks(n, "dog"),
    "variant_cat":           lambda n: _variant_pathogenicity_tasks(n, "cat"),
    "sequencing_qc_cancer":  lambda n: _sequencing_qc_tasks(n, "cancer"),
    "sequencing_qc_rare":    lambda n: _sequencing_qc_tasks(n, "rare_disease"),
}

DOMAIN_FILTERS = {
    "cancer":         {"neoantigen_prediction", "structure_cancer", "sequencing_qc_cancer"},
    "drug_discovery": {"structure_drug", "qsar", "molecular_docking"},
    "rare_disease":   {"variant_pathogenicity", "sequencing_qc_rare"},
    "canine":         {"neoantigen_dog", "variant_dog", "sequencing_qc_cancer"},
    "feline":         {"neoantigen_cat", "variant_cat", "sequencing_qc_cancer"},
}

# Skills that require local data files (VCF, FASTQ).  Excluded when
# data_mode="public" so compute isn't wasted on guaranteed-synthetic results.
LOCAL_DATA_SKILLS: set[str] = {
    "neoantigen_prediction",
    "neoantigen_dog",
    "neoantigen_cat",
    "sequencing_qc_cancer",
    "sequencing_qc_rare",
}


# ── Public API ───────────────────────────────────────────────────────────────

def generate_batch(
    count: int = 100,
    domain: str | None = None,
    species: str | None = None,
    config_path: str | None = None,
    seed: int | None = None,
    data_mode: str | None = None,
) -> list[BatchTask]:
    """Generate a batch of parameterized research tasks.

    Args:
        count:       Total number of tasks to generate.
        domain:      Filter to a single domain ("cancer", "drug_discovery", "rare_disease",
                     "canine", "feline").  None = all domains.
        species:     Shortcut for veterinary species: "dog" or "cat".  Sets domain
                     to "canine" or "feline" automatically when provided.
        config_path: Path to a YAML config with custom task templates.
                     Falls back to built-in defaults if absent.
        seed:        Random seed for reproducibility.
        data_mode:   "public" to exclude skills requiring local files (VCF/FASTQ),
                     "mydata" to include all, None for backward compatibility (all).

    Returns:
        List of BatchTask objects ready for batch_queue.submit_batch().
    """
    if seed is not None:
        random.seed(seed)

    # Species shortcut
    if species == "dog" and domain is None:
        domain = "canine"
    elif species == "cat" and domain is None:
        domain = "feline"

    # Load distribution — from YAML config or built-in defaults
    if config_path and Path(config_path).exists():
        distribution, custom_tasks, local_data_skills = _load_yaml_config(config_path)
    else:
        distribution = dict(DEFAULT_DISTRIBUTION)
        custom_tasks = []
        local_data_skills = LOCAL_DATA_SKILLS

    # Filter by domain if requested
    if domain:
        allowed = DOMAIN_FILTERS.get(domain, set())
        distribution = {k: v for k, v in distribution.items() if k in allowed}

    # Filter out skills requiring local data when running in public-database mode
    if data_mode == "public":
        excluded = {k for k in distribution if k in local_data_skills}
        if excluded:
            logger.info("Public data mode: excluding local-data skills %s", excluded)
        distribution = {k: v for k, v in distribution.items() if k not in local_data_skills}

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


def _load_yaml_config(config_path: str) -> tuple[dict, list[BatchTask], set[str]]:
    """Load task distribution, custom tasks, and local-data skills from YAML config."""
    with open(config_path) as f:
        cfg = yaml.safe_load(f) or {}

    distribution = cfg.get("distribution", dict(DEFAULT_DISTRIBUTION))

    local_data_skills = set(cfg.get("requires_local_data", LOCAL_DATA_SKILLS))

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

    return distribution, custom_tasks, local_data_skills


# ── CLI entry point ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Generate batch research tasks")
    parser.add_argument("--count", type=int, default=100, help="Number of tasks")
    parser.add_argument("--domain", choices=["cancer", "drug_discovery", "rare_disease", "canine", "feline"])
    parser.add_argument("--species", choices=["human", "dog", "cat"], help="Species shortcut (sets domain)")
    parser.add_argument("--config", help="Path to research_tasks.yaml")
    parser.add_argument("--seed", type=int, help="Random seed")
    parser.add_argument("--data-mode", choices=["public", "mydata"], help="Data source mode")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    batch = generate_batch(
        count=args.count,
        domain=args.domain,
        species=args.species,
        config_path=args.config,
        seed=args.seed,
        data_mode=args.data_mode,
    )

    if args.json:
        print(json.dumps([t.to_dict() for t in batch], indent=2, default=str))
    else:
        for i, t in enumerate(batch, 1):
            print(f"[{i:3d}] {t.domain:15s} | {t.skill_name:25s} | {t.label}")
        print(f"\nTotal: {len(batch)} tasks")
