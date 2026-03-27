# OpenCure Labs — Scientific Skills Reference

## Overview

LabClaw skills are the computational units of OpenCure Labs. Each skill wraps a
scientific workflow — neoantigen prediction, molecular docking, QSAR modeling,
etc. — behind a uniform interface with Pydantic-validated inputs/outputs, compute
routing, and automatic database logging.

All skills:
- Inherit from `LabClawSkill(ABC)` in `packages/agentiq_labclaw/agentiq_labclaw/base.py`
- Register via the `@labclaw_skill()` decorator into a global registry
- Implement a `run(input_data: BaseModel) -> BaseModel` method
- Include `novel: bool` and `critique_required: bool` in their output for the reviewer pipeline
- Can reroute to Vast.ai GPU instances via `LABCLAW_COMPUTE=vast_ai` + `VAST_AI_KEY`

---

## Skill Registry

| # | Name | Class | GPU | Dependencies |
|---|---|---|---|---|
| 1 | `neoantigen_prediction` | `NeoantigenSkill` | No | pysam, pyensembl, mhcflurry, BioPython |
| 2 | `molecular_docking` | `MolecularDockingSkill` | Yes | Open Babel, AutoDock Vina / Gnina |
| 3 | `qsar` | `QSARSkill` | No | RDKit, scikit-learn |
| 4 | `structure_prediction` | `StructurePredictionSkill` | Yes | ESMFold API, AlphaFold DB API |
| 5 | `variant_pathogenicity` | `VariantPathogenicitySkill` | No | ClinVarConnector, CADD API |
| 6 | `register_source` | `RegisterSourceSkill` | No | PostgreSQL |
| 7 | `report_generator` | `ReportGeneratorSkill` | No | reportlab |
| 8 | `sequencing_qc` | `SequencingQCSkill` | No | fastp |

---

## Base Class: LabClawSkill

**File:** `packages/agentiq_labclaw/agentiq_labclaw/base.py`

### Class Attributes

| Attribute | Type | Default | Purpose |
|---|---|---|---|
| `name` | `str` | `""` | Registered skill name |
| `description` | `str` | `""` | Human-readable description |
| `compute` | `str` | `"local"` | `"local"` or `"vast_ai"` |
| `gpu_required` | `bool` | `False` | Whether GPU is needed |
| `input_schema` | `type[BaseModel] \| None` | `None` | Pydantic input model |
| `output_schema` | `type[BaseModel] \| None` | `None` | Pydantic output model |

### Execution Flow

```
execute(input_data)
    │
    ├─ Check LABCLAW_COMPUTE env var
    ├─ Check self.compute attribute
    │
    ├─ If "vast_ai" and VAST_AI_KEY set:
    │      └─ _dispatch_to_vast_ai(input_data)
    │              └─ agentiq_labclaw.compute.vast_dispatcher.dispatch()
    │
    └─ Otherwise:
           └─ run(input_data)  ← abstract, each skill implements this
```

### Decorator: `@labclaw_skill()`

Registers the class in the global `_SKILL_REGISTRY` dict and sets class-level
attributes:

```python
@labclaw_skill(
    name="neoantigen_prediction",
    description="Predicts neoantigens from somatic variant calls",
    input_schema=NeoantigenInput,
    output_schema=NeoantigenOutput,
    compute="local",
    gpu_required=False,
)
class NeoantigenSkill(LabClawSkill):
    ...
```

### Registry Functions

- `get_skill(name: str)` → returns skill class or `None`
- `list_skills()` → returns dict of all registered skills

---

## Skill 1: Neoantigen Prediction

**File:** `packages/agentiq_labclaw/agentiq_labclaw/skills/neoantigen.py`  
**Registered name:** `neoantigen_prediction`  
**Compute:** CPU  
**External tools:** pysam, pyensembl (Ensembl release 110), mhcflurry, BioPython

### Constants

| Name | Value | Purpose |
|---|---|---|
| `STRONG_BINDER_IC50` | `500.0` nM | Strong MHC-I binder threshold |
| `WEAK_BINDER_IC50` | `5000.0` nM | Weak binder threshold |
| `PEPTIDE_LENGTHS` | `(8, 9, 10, 11)` | Peptide window sizes |
| `ENSEMBL_RELEASE` | `110` | Ensembl annotation version |

### Input: `NeoantigenInput`

| Field | Type | Default | Description |
|---|---|---|---|
| `sample_id` | `str` | required | Sample identifier |
| `vcf_path` | `str` | required | Path to somatic VCF file |
| `hla_alleles` | `list[str]` | required | HLA alleles (e.g. `["HLA-A*02:01"]`) |
| `tumor_type` | `str` | required | Tumor type label |

### Intermediate: `NeoantigenCandidate`

| Field | Type | Description |
|---|---|---|
| `gene` | `str` | Gene symbol |
| `transcript_id` | `str` | Ensembl transcript ID |
| `variant` | `str` | Genomic variant (e.g. `"chr17:7674220 C>T"`) |
| `mutation` | `str` | Protein-level mutation (e.g. `"R248W"`) |
| `wildtype_peptide` | `str` | Reference peptide sequence |
| `mutant_peptide` | `str` | Mutant peptide sequence |
| `peptide_length` | `int` | Window length |
| `hla_allele` | `str` | HLA allele tested against |
| `ic50_mt` | `float` | Mutant IC50 in nM |
| `ic50_wt` | `float` | Wildtype IC50 in nM |
| `fold_change` | `float` | wt/mt ratio |
| `agretopicity` | `float` | ic50_wt / ic50_mt |
| `binding_category` | `str` | `"strong"`, `"weak"`, or `"non-binder"` |

### Output: `NeoantigenOutput`

| Field | Type | Description |
|---|---|---|
| `sample_id` | `str` | Sample identifier |
| `candidates` | `list[dict]` | All binder candidates |
| `top_candidate` | `dict` | Lowest IC50 candidate |
| `confidence_score` | `float` | Fraction of strong binders |
| `novel` | `bool` | True if strong binders exist |
| `critique_required` | `bool` | True if strong binders exist |

### Pipeline Steps

1. **Log start** — records pipeline run in PostgreSQL
2. **Parse VCF** — `pysam.VariantFile`, filtered to PASS variants
3. **Transcript lookup** — pyensembl maps genomic position → CDS offset → mutant amino acid (via `Bio.Seq.translate()`), skips synonymous mutations
4. **Generate peptide windows** — slides windows of length 8–11 across the mutation site, produces WT/mutant peptide pairs
5. **MHC-I binding prediction** — batch `mhcflurry.Class1AffinityPredictor.predict()` for all peptides × alleles, classifies by IC50 thresholds
6. **Rank** — sort candidates by IC50 ascending, filter to binders only
7. **Return** — structured output with binders, top candidate, confidence, and reviewer flags

### Helper Functions

| Function | Purpose |
|---|---|
| `_normalize_allele(allele)` | Normalizes to `HLA-A*02:01` format |
| `_parse_vcf_variants(vcf_path)` | Parses VCF, returns variant dicts |
| `_get_affected_transcripts(...)` | Looks up protein-coding transcripts at locus |
| `_genomic_to_coding_offset(...)` | 1-based genomic → 0-based CDS offset |
| `_mutate_codon(...)` | Computes mutant amino acid at codon |
| `_generate_peptide_windows(...)` | Generates WT/mutant peptide pairs |
| `_predict_binding(...)` | Batch MHCflurry binding prediction |

### CLI Usage

```bash
python pipelines/run_pipeline.py neoantigen \
  --vcf data/sample.vcf \
  --hla "HLA-A*02:01,HLA-B*07:02" \
  --sample-id SAMPLE001 \
  --tumor-type NSCLC
```

---

## Skill 2: Molecular Docking

**File:** `packages/agentiq_labclaw/agentiq_labclaw/skills/docking.py`  
**Registered name:** `molecular_docking`  
**Compute:** Local GPU  
**External tools:** Open Babel (`obabel`), AutoDock Vina (`vina`), Gnina (`gnina`)

### Input: `DockingInput`

| Field | Type | Default | Description |
|---|---|---|---|
| `ligand_smiles` | `str` | required | SMILES string for ligand |
| `receptor_pdb` | `str` | required | Path to receptor PDB file |
| `center_x` | `float` | required | Search box center X |
| `center_y` | `float` | required | Search box center Y |
| `center_z` | `float` | required | Search box center Z |
| `box_size` | `float` | `20.0` | Search box size (Å) |
| `exhaustiveness` | `int` | `8` | Exhaustiveness parameter |
| `method` | `str` | `"vina"` | `"vina"` or `"gnina"` |

### Output: `DockingOutput`

| Field | Type | Description |
|---|---|---|
| `ligand_smiles` | `str` | Input SMILES |
| `receptor_pdb` | `str` | Receptor path |
| `binding_affinity_kcal` | `float` | Best affinity (kcal/mol) |
| `pose_pdb_path` | `str` | Path to output PDBQT file |
| `method_used` | `str` | `"vina"` or `"gnina"` |
| `novel` | `bool` | True if affinity < -8.0 |
| `critique_required` | `bool` | True if affinity < -7.0 |

### Pipeline Steps

1. **Prepare ligand** — SMILES → SDF (3D coords via `obabel --gen3d`) → PDBQT
2. **Prepare receptor** — PDB → PDBQT via `obabel -xr`
3. **Define search box** — center coordinates + box_size
4. **Run docking** — subprocess call to `vina` or `gnina` (600s timeout)
5. **Parse results** — extract best binding affinity, copy pose to `reports/docking/`

### CLI Usage

```bash
python pipelines/run_pipeline.py drug_screen \
  --smiles "CC(=O)Oc1ccccc1C(O)=O" \
  --receptor data/target.pdb \
  --center-x 0 --center-y 0 --center-z 0 \
  --similarity 70 --max-candidates 10
```

---

## Skill 3: QSAR Modeling

**File:** `packages/agentiq_labclaw/agentiq_labclaw/skills/qsar.py`  
**Registered name:** `qsar`  
**Compute:** CPU  
**External tools:** RDKit, scikit-learn

### RDKit Descriptors (10)

| Descriptor | Function |
|---|---|
| `MolWt` | `Descriptors.MolWt` |
| `LogP` | `Descriptors.MolLogP` |
| `TPSA` | `Descriptors.TPSA` |
| `NumHDonors` | `Descriptors.NumHDonors` |
| `NumHAcceptors` | `Descriptors.NumHAcceptors` |
| `NumRotatableBonds` | `Descriptors.NumRotatableBonds` |
| `RingCount` | `Descriptors.RingCount` |
| `FractionCSP3` | `Descriptors.FractionCSP3` |
| `HeavyAtomCount` | `Descriptors.HeavyAtomCount` |
| `NumAromaticRings` | `Descriptors.NumAromaticRings` |

### Input: `QSARInput`

| Field | Type | Default | Description |
|---|---|---|---|
| `dataset_path` | `str` | required | Path to CSV dataset |
| `target_column` | `str` | required | Target variable column |
| `smiles_column` | `str` | `"smiles"` | SMILES column name |
| `model_type` | `str` | `"random_forest"` | `"random_forest"` or `"xgboost"` |
| `mode` | `str` | `"train"` | `"train"` or `"predict"` |
| `model_path` | `str \| None` | `None` | Saved model path (predict mode) |

### Output: `QSAROutput`

| Field | Type | Description |
|---|---|---|
| `model_path` | `str` | Path to saved/loaded model |
| `metrics` | `dict` | Performance metrics (R², CV scores) |
| `predictions` | `list[dict] \| None` | Predictions (predict mode) |
| `novel` | `bool` | True if R² > 0.7 |
| `critique_required` | `bool` | True for train, False for predict |

### Pipeline Steps

**Train mode:**
1. Load CSV, compute RDKit descriptors for each SMILES
2. Select model: `RandomForestRegressor(n_estimators=200, max_depth=10)` or `GradientBoostingRegressor(n_estimators=200, max_depth=5)`, both `random_state=42`
3. 5-fold cross-validation with R² scoring, then `model.fit(X, y)`
4. Pickle model + descriptor names to `reports/qsar_models/qsar_{type}.pkl`

**Predict mode:**
1. Load pickled model from `model_path`
2. Compute descriptors for each row, call `model.predict()`, return `[{"smiles": ..., "predicted": ...}]`

---

## Skill 4: Structure Prediction

**File:** `packages/agentiq_labclaw/agentiq_labclaw/skills/structure.py`  
**Registered name:** `structure_prediction`  
**Compute:** Local GPU  
**External APIs:** ESMFold (`api.esmatlas.com`), AlphaFold DB (`alphafold.ebi.ac.uk`)

### Input: `StructureInput`

| Field | Type | Default | Description |
|---|---|---|---|
| `protein_id` | `str` | required | Protein / UniProt identifier |
| `sequence` | `str` | required | Amino acid sequence |
| `method` | `str` | `"esmfold"` | `"esmfold"` or `"alphafold"` |

### Output: `StructureOutput`

| Field | Type | Description |
|---|---|---|
| `protein_id` | `str` | Protein identifier |
| `pdb_path` | `str` | Path to output PDB file |
| `confidence_score` | `float` | Mean pLDDT / 100 (0–1) |
| `method_used` | `str` | Method used |
| `novel` | `bool` | True if confidence > 0.7 (ESMFold) |
| `critique_required` | `bool` | Always True |

### Pipeline Steps

**ESMFold path:**
1. Validate and uppercase sequence
2. POST to `https://api.esmatlas.com/foldSequence/v1/pdb/` (120s timeout)
3. Parse pLDDT from B-factor column, compute mean, normalize to 0–1
4. Save PDB to `reports/structures/{protein_id}_esmfold.pdb`

**AlphaFold path:**
1. GET `https://alphafold.ebi.ac.uk/api/prediction/{accession}` (30s timeout)
2. If 404 or empty → fallback to ESMFold
3. Download PDB, extract global pLDDT metric, save to `{accession}_alphafold.pdb`

---

## Skill 5: Variant Pathogenicity

**File:** `packages/agentiq_labclaw/agentiq_labclaw/skills/variant_pathogenicity.py`  
**Registered name:** `variant_pathogenicity`  
**Compute:** CPU  
**External tools:** ClinVarConnector, CADD REST API

### ACMG Thresholds

| Threshold | Value |
|---|---|
| `CADD_PATHOGENIC_THRESHOLD` | `25.0` |
| `CADD_LIKELY_PATHOGENIC_THRESHOLD` | `20.0` |
| `CADD_LIKELY_BENIGN_THRESHOLD` | `10.0` |

### Input: `VariantInput`

| Field | Type | Default | Description |
|---|---|---|---|
| `variant_id` | `str` | required | e.g. `"chr17:7674220:C>T"` |
| `gene` | `str` | required | Gene symbol |
| `transcript` | `str \| None` | `None` | Transcript ID |
| `hgvs` | `str \| None` | `None` | HGVS notation |

### Output: `VariantOutput`

| Field | Type | Description |
|---|---|---|
| `variant_id` | `str` | Input variant ID |
| `gene` | `str` | Gene symbol |
| `clinvar_significance` | `str \| None` | ClinVar clinical significance |
| `omim_associations` | `list[dict]` | Gene-disease associations |
| `pathogenicity_score` | `float` | Aggregated score (0–1) |
| `classification` | `str` | ACMG classification |
| `novel` | `bool` | True if no ClinVar entry + classified pathogenic |
| `critique_required` | `bool` | True if pathogenic, likely_pathogenic, or VUS |

### Classification Logic

ClinVar significance takes priority when available. Falls back to CADD PHRED
score thresholds. When both present, score = `max(clinvar_weight, cadd/40)`.

| Classification | CADD PHRED | ClinVar |
|---|---|---|
| `pathogenic` | ≥ 25 | `Pathogenic` |
| `likely_pathogenic` | 20–25 | `Likely pathogenic` |
| `vus` | 10–20 | `Uncertain significance` |
| `likely_benign` | < 10 | `Likely benign` |
| `benign` | — | `Benign` |

---

## Skill 6: Register Source

**File:** `packages/agentiq_labclaw/agentiq_labclaw/skills/register_source.py`  
**Registered name:** `register_source`  
**Compute:** CPU  
**External tools:** PostgreSQL

### Input: `RegisterSourceInput`

| Field | Type | Default | Description |
|---|---|---|---|
| `url` | `str` | required | URL of discovered data source |
| `domain` | `str` | required | Scientific domain |
| `discovered_by` | `str` | `"grok"` | Discovering agent |
| `notes` | `str \| None` | `None` | Free-text notes |

### Output: `RegisterSourceOutput`

| Field | Type | Description |
|---|---|---|
| `source_id` | `int` | DB-assigned ID |
| `url` | `str` | Source URL |
| `domain` | `str` | Domain |
| `registered` | `bool` | Always True |
| `novel` | `bool` | Always True |
| `critique_required` | `bool` | Always False |

### Logic

Calls `agentiq_labclaw.db.discovered_sources.register_source()` and returns the
DB-assigned source ID. Used primarily by the Grok agent to queue datasets for
coordinator review.

---

## Skill 7: Report Generator

**File:** `packages/agentiq_labclaw/agentiq_labclaw/skills/report_generator.py`  
**Registered name:** `report_generator`  
**Compute:** CPU  
**External tools:** reportlab

### Input: `ReportInput`

| Field | Type | Default | Description |
|---|---|---|---|
| `title` | `str` | required | Report title |
| `pipeline_run_id` | `int` | required | Pipeline run ID |
| `sections` | `list[dict]` | required | Sections with heading, content, table, figures |
| `critique_json` | `dict \| None` | `None` | Reviewer critique to append |
| `output_dir` | `str` | `"/path/to/OpenCureLabs/reports/"` | Output directory |

### Output: `ReportOutput`

| Field | Type | Description |
|---|---|---|
| `pdf_path` | `str` | Path to generated PDF |
| `page_count` | `int` | Approximate page count |
| `novel` | `bool` | Always False |
| `critique_required` | `bool` | Always False |

### Logic

Builds a PDF using `SimpleDocTemplate` (A4, 2cm margins). Iterates sections,
adding styled headings, body paragraphs, and tables with blue header rows and
alternating row colors. Appends critique section if provided. Output filename:
`{title}_{YYYYMMDD_HHMMSS}.pdf`.

---

## Skill 8: Sequencing QC

**File:** `packages/agentiq_labclaw/agentiq_labclaw/skills/sequencing_qc.py`  
**Registered name:** `sequencing_qc`  
**Compute:** CPU  
**External tools:** fastp

### QC Thresholds

| Threshold | Value |
|---|---|
| `MIN_MEAN_QUALITY` | `20.0` |
| `MAX_ADAPTER_PCT` | `5.0` |
| `MIN_GC_CONTENT` | `30.0` |
| `MAX_GC_CONTENT` | `70.0` |

### Input: `SequencingQCInput`

| Field | Type | Default | Description |
|---|---|---|---|
| `sample_id` | `str` | required | Sample identifier |
| `fastq_paths` | `list[str]` | required | 1–2 FASTQ paths (SE or PE) |
| `reference_genome` | `str` | `"hg38"` | Reference genome build |

### Output: `SequencingQCOutput`

| Field | Type | Description |
|---|---|---|
| `sample_id` | `str` | Sample ID |
| `total_reads` | `int` | Total reads before filtering |
| `mean_quality` | `float` | Mean base quality |
| `gc_content` | `float` | GC content (%) |
| `adapter_contamination_pct` | `float` | Adapter contamination (%) |
| `pass_qc` | `bool` | Pass/fail |
| `qc_report_path` | `str` | Path to HTML report |
| `novel` | `bool` | Always False |
| `critique_required` | `bool` | True if QC failed |

### Pipeline Steps

1. **Run fastp** — subprocess: `fastp --json {json} --html {html} --in1 {R1} [--in2 {R2}]` (600s timeout)
2. **Parse JSON** — extract total reads, Q30 rate, GC content, adapter trim counts
3. **Apply thresholds** — `pass = quality ≥ 20 AND adapter ≤ 5% AND 30% ≤ GC ≤ 70%`
4. **Return** — structured output with pass/fail and HTML report path

---

## Pipelines

Pipelines chain multiple skills together with PostgreSQL logging.

### Pipeline Runner

**File:** `pipelines/run_pipeline.py`

All pipelines log start/end to `pipeline_runs` table and results to
`experiment_results` table.

#### Neoantigen Pipeline

```bash
python pipelines/run_pipeline.py neoantigen \
  --vcf data/sample.vcf \
  --hla "HLA-A*02:01,HLA-B*07:02" \
  --sample-id SAMPLE001 \
  --tumor-type NSCLC
```

Runs: VCF → `NeoantigenSkill.run()` → log result → complete

#### Variant Discovery Pipeline

```bash
python pipelines/run_pipeline.py variant_discovery \
  --variant "chr17:7674220:C>T" \
  --gene TP53 \
  --transcript ENST00000269305
```

Runs: Variant → `VariantPathogenicitySkill.run()` → if pathogenic: `ReportGeneratorSkill.run()` (PDF with Summary, ClinVar, OMIM sections) → log → complete

#### Drug Screening Pipeline

```bash
python pipelines/run_pipeline.py drug_screen \
  --smiles "CC(=O)Oc1ccccc1C(O)=O" \
  --receptor data/target.pdb \
  --center-x 0 --center-y 0 --center-z 0 \
  --similarity 70 --max-candidates 10
```

Runs: SMILES → `ChEMBLConnector.search_compound()` → for each candidate: `MolecularDockingSkill.run()` → sort by affinity → log → complete

### Evaluation Framework

**File:** `pipelines/eval_mode.py`

End-to-end benchmark suite with 5 predefined test cases:

| Case | Suite | Validators |
|---|---|---|
| `neoantigen_tp53_basic` | neoantigen | sample_id, candidates type, confidence range, novel type |
| `variant_tp53_pathogenic` | variant | classification in {pathogenic, likely_pathogenic}, score 0.5–1.0 |
| `structure_esmfold_short` | structure | method_used, confidence range, pdb_path suffix |
| `qsar_descriptors` | qsar | descriptor computation on 3 molecules |
| `report_basic_pdf` | report | pdf_path suffix, page_count ≥ 1 |

```bash
python pipelines/eval_mode.py --suite neoantigen --verbose
python pipelines/eval_mode.py  # runs all suites
```

Output: summary table + `reports/eval_results.json`

---

## Dynamic Task Derivation — Chain Thresholds

When a skill produces a result that exceeds a confidence threshold, the ingest
worker automatically spawns follow-up tasks using related skills. This creates
a chain of progressively deeper analysis.

### Chain Threshold Configuration

Defined in `workers/ingest/tasks.ts` as `CHAIN_THRESHOLDS`:

| Skill | Metric | Threshold | Follow-up Skills |
|---|---|---|---|
| `neoantigen_prediction` | `confidence_score` | ≥ 0.7 | `structure_prediction`, `molecular_docking` |
| `structure_prediction` | `confidence_score` | ≥ 0.6 | `molecular_docking` |
| `molecular_docking` | `binding_affinity_kcal` | ≤ -8.0 | `qsar` |
| `variant_pathogenicity` | `pathogenicity_score` | ≥ 0.7 | `structure_prediction`, `neoantigen_prediction` |

### How Skills Connect in Chains

```
neoantigen_prediction (novel strong binder found)
    │ confidence ≥ 0.7
    ├──→ structure_prediction (predict protein structure for the gene)
    │        │ confidence ≥ 0.6
    │        └──→ molecular_docking (dock candidate against predicted structure)
    │                 │ affinity ≤ -8.0
    │                 └──→ qsar (build QSAR model from docking results)
    │
    └──→ molecular_docking (dock against known receptor)

variant_pathogenicity (pathogenic variant found)
    │ score ≥ 0.7
    ├──→ structure_prediction (predict impact on protein)
    └──→ neoantigen_prediction (check for neoantigen potential)
```

### Discovery-Driven Tasks

The `grok_research` skill (Grok literature monitoring) can also spawn tasks when
it discovers new gene or drug targets. These get `source: "discovery"` in the
tasks table.

### Guardrails

- Max chain depth: 4 steps
- Max 20 derived tasks per result
- Derived tasks use `priority: 2` (higher than bank tasks)
- Results must be `novel` to trigger derivation
- `input_hash` deduplication prevents duplicate derived tasks
