# Veterinary Genomics — Multi-Species Support

> **Status:** Implemented (task routing, DB schema, dashboard filtering); core pipeline species-gating in progress  
> **Target species:** Canine (*Canis lupus familiaris*), Feline (*Felis catus*)  
> **Use case:** Personalized cancer vaccine design for veterinary oncology

---

## Background

A developer [designed an mRNA vaccine to treat his dog's cancer](https://reason.com/2026/03/19/man-successfully-designs-mrna-vaccine-to-treat-his-dogs-cancer/)
using open-source tools. He proved one person with the right pipeline can do
what takes an institution months.

OpenCure Labs is building the infrastructure so anyone, anywhere can run that
same pipeline — and push it further. This document describes the plan to extend
our human neoantigen prediction pipeline to support canine and feline genomes,
enabling veterinary cancer vaccine design.

The neoantigen prediction pipeline works by:
1. Parsing somatic mutations from tumor sequencing (VCF)
2. Looking up affected transcripts and protein sequences
3. Generating mutant peptide windows (8–11mers) around each mutation
4. Scoring MHC binding affinity to predict which peptides the immune system can target
5. Ranking candidates — strong binders become vaccine targets

This process is fundamentally species-agnostic. The biology is the same in dogs,
cats, and humans. What differs is the reference genome, gene annotations, and
MHC allele system.

---

## Current State Audit

### What's already species-agnostic
| Component | Tool | Status |
|---|---|---|
| Protein structure prediction | ESMFold / AlphaFold | Works on any amino acid sequence |
| Molecular docking | AutoDock Vina / Gnina | Species-agnostic |
| QSAR modeling | scikit-learn / RDKit | Species-agnostic |
| Peptide window generation | Internal | Species-agnostic |
| IC50 binding thresholds | Biophysical constants | Species-agnostic |
| Sequencing QC | fastp | Species-agnostic |

### What's currently human-only (17 hardcoded assumptions)

| Component | File | Issue |
|---|---|---|
| Ensembl release | `neoantigen.py` L33, L120 | `EnsemblRelease(110)` — no species parameter |
| HLA allele normalization | `neoantigen.py` L84-86 | `_normalize_allele()` assumes HLA prefix |
| MHC binding predictor | `neoantigen.py` L310-320, L421-430 | MHCflurry is human HLA-only |
| NeoantigenInput schema | `neoantigen.py` L41-44 | No `species` field |
| Chromosome handling | `neoantigen.py` L122 | `chrom.replace("chr", "")` — human convention |
| CADD API | `variant_pathogenicity.py` L42-43 | Hardcoded to `/score/GRCh38/` |
| ClinVar integration | `variant_pathogenicity.py` L129-137 | Human-only database |
| Reference genome default | `sequencing_qc.py` L28 | `reference_genome: str = "hg38"` |
| Cancer gene bank | `task_generator.py` L48-62 | 15 human genes with human coordinates |
| Rare disease variants | `task_generator.py` L98-113 | 15 human chromosomal positions |
| HLA allele panels | `task_generator.py` L71-76 | Human HLA haplotypes |
| Reference genome in tasks | `task_generator.py` L265 | `"reference_genome": "hg38"` |
| TCGA data source | `cancer_agent.yaml` L9 | Human cancer genomics only |
| ClinVar data source | `rare_disease_agent.yaml` L9 | Human-only |
| Test VCF | `tests/data/synthetic_somatic.vcf` L3 | `##reference=GRCh38` |

---

## Available Open-Source Resources

### Canine (Dog)

| Resource | Description | Access |
|---|---|---|
| **CanFam3.1 / CanFam4** | Dog reference genome (Boxer / German Shepherd) | NCBI GCF_000002285.3 / GCF_011100685.1 |
| **Ensembl (dog)** | Gene annotations, transcripts, protein sequences | `pyensembl install --release 111 --species dog` |
| **DLA alleles** | Dog Leukocyte Antigen — canine MHC system | IPD-MHC Database (ebi.ac.uk/ipd/mhc) |
| **mhcgnomes** | MHC nomenclature parser (DLA-88, DQA1, DQB1, DRA, DRB1) | Already installed (v3.10.0) |
| **OMIA** | Online Mendelian Inheritance in Animals | omia.org (REST API) |
| **DBVDC** | Database of Variants in Canine Cancer | NCBI SRA datasets |
| **DoGSD** | Dog Genome SNP Database | dogsd.big.ac.cn |

### Feline (Cat)

| Resource | Description | Access |
|---|---|---|
| **felCat9** | Cat reference genome | NCBI GCF_000181335.3 |
| **Ensembl (cat)** | Gene annotations | `pyensembl install --release 111 --species cat` |
| **99 Lives Project** | Large-scale cat WGS consortium | felinegenetics.missouri.edu |
| **FLA alleles** | Feline Leukocyte Antigen (limited characterization) | IPD-MHC Database |
| **OMIA** | Feline genetic diseases | omia.org |

### Cross-Species Tools

| Tool | Status | Notes |
|---|---|---|
| **pyensembl** (v2.3.13) | Already installed | Supports dog via `EnsemblRelease(111, species="dog")` + cat, mouse, 20+ species |
| **mhcgnomes** (v3.10.0) | Already installed | Parses DLA/FLA allele nomenclature for 100+ species |
| **NetMHCpan 4.1** | Needs install | Cross-species MHC-I binding prediction; requires free academic license from DTU |
| **Ensembl VEP REST API** | Available | Species-agnostic variant effect prediction (SIFT, PolyPhen2) |
| **MHCflurry** (v2.1.5) | Already installed | Human HLA-only — cannot predict canine/feline binding |

---

## Common Canine Cancer Mutations

These are the most actionable somatic mutations in veterinary oncology:

| Gene | Cancer Type | Mutation | Prevalence | Notes |
|---|---|---|---|---|
| **BRAF** | Transitional cell carcinoma (bladder) | V595E (equivalent to human V600E) | ~85% of canine TCC | Most actionable — well-characterized |
| **KIT** | Mast cell tumor | Exon 11 internal tandem duplications | ~30-50% of MCT | Targetable with toceranib (Palladia) |
| **TP53** | Osteosarcoma, mammary tumors | Various loss-of-function | ~40% of OSA | Same gene, different hotspot positions |
| **BRCA1/2** | Mammary tumors | Various | Variable | Orthologous to human BRCA |
| **PTEN** | Hemangiosarcoma | Loss-of-function | ~30% | PI3K pathway |
| **MC1R** | Oral melanoma | Various | Variable | Immunotherapy target |
| **PDGFRA** | Gastrointestinal stromal tumor | Activating mutations | Rare | Same pathway as human GIST |
| **PIK3CA** | Various carcinomas | Activating mutations | Variable | mTOR pathway |

### Dog Leukocyte Antigen (DLA) System

The DLA system is the canine equivalent of human HLA:

| DLA Gene | Human Equivalent | Class | Characterized Alleles |
|---|---|---|---|
| DLA-88 | HLA-A/B/C | Class I | ~100 alleles |
| DLA-12 | HLA-A/B/C | Class I | ~20 alleles |
| DLA-64 | HLA-A/B/C | Class I | ~15 alleles |
| DLA-DQA1 | HLA-DQA1 | Class II | ~20 alleles |
| DLA-DQB1 | HLA-DQB1 | Class II | ~60 alleles |
| DLA-DRB1 | HLA-DRB1 | Class II | ~100 alleles |

**Key difference from human:** Far fewer characterized alleles (~300 total vs
~35,000 for human HLA). This means binding prediction accuracy will be lower,
but the pan-allele models in NetMHCpan can extrapolate from training data.

---

## Implementation Plan

### Phase 1: Species Abstraction Layer
*No dependencies — start here*

**1. Create `species.py` registry module**

New file: `packages/agentiq_labclaw/agentiq_labclaw/species.py`

- `SpeciesConfig` dataclass: `name`, `latin`, `ensembl_species`, `ensembl_release`,
  `reference_genome`, `mhc_prefix`, `mhc_class1_genes`, `chromosome_prefix`,
  `supported_mhc_predictor`
- Pre-built configs:
  - **HUMAN:** `ensembl_species="homo_sapiens"`, `reference_genome="GRCh38"`,
    `mhc_prefix="HLA"`, `ensembl_release=110`
  - **DOG:** `ensembl_species="canis_familiaris"`, `reference_genome="CanFam3.1"`,
    `mhc_prefix="DLA"`, `ensembl_release=111`
  - **CAT:** `ensembl_species="felis_catus"`, `reference_genome="felCat9"`,
    `mhc_prefix="FLA"`, `ensembl_release=111`
- Lookup: `get_species(name: str) -> SpeciesConfig`

**2. Add `species` field to all input schemas**

- `NeoantigenInput`: add `species: str = "human"`
- `VariantInput`: add `species: str = "human"`
- `SequencingQCInput`: derive `reference_genome` default from species
- `StructureInput`: add `species: str = "human"` (for AlphaFold organism filtering)
- All default to `"human"` — zero breaking changes.

### Phase 2: Neoantigen Pipeline Adaptation
*Depends on Phase 1*

**3. Update pyensembl initialization** (`neoantigen.py`)

Replace:
```python
ENSEMBL_RELEASE = 110
ensembl = EnsemblRelease(ENSEMBL_RELEASE)
```
With:
```python
species_config = get_species(input_data.species)
ensembl = EnsemblRelease(species_config.ensembl_release, species=species_config.ensembl_species)
```

Ensembl auto-downloads annotation data for the species on first run. Dog data is
~2 GB (GTF + transcript FASTA + protein FASTA).

**4. Refactor MHC allele normalization**

Make `_normalize_allele()` species-aware:
- Human: normalize to `HLA-A*02:01` format (existing)
- Dog: normalize to `DLA-88*001:01` format
- Cat: normalize to `FLA-K*001` format
- Validate with `mhcgnomes.parse()` (already installed)

**5. Create MHC binding predictor abstraction**

New file: `packages/agentiq_labclaw/agentiq_labclaw/skills/mhc_predictor.py`

- `MHCPredictor` base class: `predict(alleles, peptides) -> list[float]`
- `MHCflurryPredictor` — wraps existing human-only MHCflurry code
- `NetMHCpanPredictor` — shells out to `netMHCpan` binary for cross-species
  MHC-I binding prediction
- Runtime detection: if NetMHCpan not installed, log warning and suggest
  fallback (closest human HLA homolog or install instructions)

**6. Update neoantigen `run()` method**

- Load species config from `input_data.species`
- Pass to pyensembl, allele normalizer, and MHC predictor
- Peptide window generation and IC50 thresholds remain unchanged —
  these are biophysically species-agnostic

### Phase 3: Variant Pathogenicity — Species Routing
*Depends on Phase 1, parallel with Phase 2*

**7. Species-aware variant annotation** (`variant_pathogenicity.py`)

- Human: CADD API + ClinVar (existing, unchanged)
- Non-human: skip CADD (GRCh38-only API), skip ClinVar (human-only database)
- Add Ensembl VEP REST API: `https://rest.ensembl.org/vep/{species}/region/...`
  — supports all Ensembl species, provides SIFT + PolyPhen2 scores

**8. Create OMIA connector** (`connectors/omia.py`)

OMIA (Online Mendelian Inheritance in Animals) is the veterinary equivalent
of ClinVar/OMIM:
- REST API: `https://omia.org/api/`
- Lookup: gene → known animal disease associations
- Filter by species (Canis lupus familiaris / Felis catus)

**9. Create Ensembl VEP connector** (`connectors/ensembl_vep.py`)

- REST API for species-agnostic variant effect prediction
- Provides SIFT + PolyPhen2 scores for any Ensembl species
- Replaces CADD for non-human variant pathogenicity scoring

### Phase 4: Veterinary Gene/Variant Banks
*Depends on Phase 1, parallel with Phases 2-3*

**10. Add canine cancer gene bank** (`task_generator.py`)

Curated list with CanFam3.1 coordinates:
- BRAF V595E (TCC), KIT exon 11 (MCT), TP53 (OSA)
- BRCA1/2 (mammary), PTEN (HSA), MC1R (melanoma)
- DLA allele panels from published veterinary immunogenomics

**11. Add feline cancer gene bank** (`task_generator.py`)

- KIT (mast cell), TP53, PDGFRA, FeLV integration sites
- FLA allele panels (limited but documented)

**12. Add `--species` flag to task generator CLI**

```bash
python3 -m agentiq_labclaw.task_generator --count 50 --species dog
```

**13. Update `config/research_tasks.yaml`** — add species selection option

### Phase 5: Agent Configs & UI
*Depends on Phases 3-4*

**14. Update agent YAML configs**

- Add species routing to `cancer_agent.yaml` and `rare_disease_agent.yaml`
- Add OMIA as data source for non-human species

**15. Add species selector to `run_research.sh`**

After selecting Cancer domain, prompt:
```
Species:
  🧑 Human
  🐕 Dog (Canine)
  🐈 Cat (Feline)
```
Pass species through to agent and task generator.

**16. Update batch mode** — add `--species` flag to batch dispatcher CLI

### Phase 6: Testing & Data Downloads
*Depends on Phase 2*

**17. Ensembl data download script**

New file: `scripts/download_ensembl_species.sh`
```bash
pyensembl install --release 111 --species dog
pyensembl install --release 111 --species cat
```

**18. Canine test data**

New file: `tests/data/synthetic_canine_somatic.vcf` — synthetic VCF with
CanFam3.1 coordinates (BRAF V595E, KIT exon 11)

**19. Canine pipeline test**

New file: `tests/test_neoantigen_canine.py` — end-to-end test:
canine VCF → pyensembl (canine) → peptide windows → binding prediction →
ranked candidates

---

## Files to Modify

| File | Changes |
|---|---|
| `skills/neoantigen.py` | pyensembl species param, allele normalization, MHCflurry → predictor abstraction, NeoantigenInput schema, chromosome handling |
| `skills/variant_pathogenicity.py` | Species routing (CADD for human, VEP for others), ClinVar skip for non-human |
| `skills/sequencing_qc.py` | Derive `reference_genome` default from species |
| `skills/structure.py` | Minor: AlphaFold organism filtering |
| `task_generator.py` | Add canine/feline gene banks, `--species` flag, species-aware generation |
| `dashboard/run_research.sh` | Species selector UI |
| `agents/cancer_agent.yaml` | Species routing, OMIA data source |
| `agents/rare_disease_agent.yaml` | Species routing |
| `config/research_tasks.yaml` | Species config option |

## New Files to Create

| File | Purpose |
|---|---|
| `agentiq_labclaw/species.py` | Species config registry (Human, Dog, Cat) |
| `agentiq_labclaw/skills/mhc_predictor.py` | MHC binding predictor abstraction |
| `connectors/omia.py` | OMIA REST API connector |
| `connectors/ensembl_vep.py` | Ensembl VEP REST API connector |
| `tests/data/synthetic_canine_somatic.vcf` | Canine test VCF data |
| `tests/test_neoantigen_canine.py` | Canine pipeline integration test |
| `scripts/download_ensembl_species.sh` | Ensembl data pre-download script |

---

## Key Decisions

### NetMHCpan vs MHCflurry
MHCflurry is trained exclusively on human HLA data. NetMHCpan 4.1 from DTU
is the only validated tool for cross-species MHC-I binding prediction. It
requires a free academic license. We implement both behind an abstraction layer
and detect available tools at runtime.

### Backward Compatibility
All existing human functionality is untouched. The `species` parameter defaults
to `"human"` everywhere. Zero breaking changes.

### Cat Support Depth
Feline MHC (FLA) is significantly less characterized than canine DLA (~50 known
alleles vs ~300). We include basic support but binding prediction accuracy will
be limited. This is a known limitation of the field, not our pipeline.

### CADD Score Replacement
CADD is human-only (GRCh38). For non-human species, we use Ensembl VEP REST API
which provides SIFT and PolyPhen2 scores for all Ensembl species. These are
established functional impact predictors.

### Scope Exclusions
- We are NOT training new ML models for canine/feline MHC binding
- We are NOT building new reference genome assemblies
- We ARE integrating existing open-source tools and public databases

---

## Verification Checklist

- [ ] `get_species("dog")` returns correct CanFam3.1 config with DLA prefix
- [ ] `pyensembl install --release 111 --species dog` succeeds
- [ ] Canine transcript lookup works for known genes (BRAF, KIT, TP53)
- [ ] DLA-88*001:01 normalizes correctly
- [ ] `mhcgnomes.parse("DLA-88*001:01")` validates
- [ ] NetMHCpan detection: graceful fallback message if not installed
- [ ] OMIA connector returns known canine cancer gene associations
- [ ] `task_generator --count 50 --species dog` produces canine-specific tasks
- [ ] Full pipeline: canine VCF → pyensembl → peptide windows → binding → ranked candidates
- [ ] Existing human tests still pass (backward compatibility)
- [ ] Species selector appears in run_research.sh UI
- [ ] Batch mode accepts `--species` parameter

---

## Cost & Resource Estimates

### Data Requirements
| Species | Ensembl Download | Disk Space |
|---|---|---|
| Dog (CanFam3.1) | GTF + cDNA + protein FASTA | ~2 GB |
| Cat (felCat9) | GTF + cDNA + protein FASTA | ~1.5 GB |

### Compute
No additional compute requirements. All tools run on existing hardware.
NetMHCpan is CPU-only. pyensembl lookups are local after initial download.

### External Dependencies
| Dependency | License | Required? |
|---|---|---|
| NetMHCpan 4.1 | Free academic (DTU) | Recommended for accurate binding prediction |
| pyensembl | Apache 2.0 | Already installed |
| mhcgnomes | Apache 2.0 | Already installed |
| Ensembl VEP REST API | Open access | No install needed |
| OMIA API | Open access | No install needed |

---

## References

- Conyngham, P. (2024). "How I designed a cancer vaccine for my dog using
  open-source bioinformatics tools."
- NetMHCpan 4.1: Reynisson et al., *Nucleic Acids Research* (2020).
  "NetMHCpan-4.1 and NetMHCIIpan-4.0: improved predictions of MHC antigen
  presentation by concurrent motif deconvolution and integration of MS
  MHC eluted ligand data."
- DLA Nomenclature: Kennedy et al., *Tissue Antigens* (2007).
  "Dog leukocyte antigen (DLA) nomenclature."
- OMIA: Nicholas, F.W. *Online Mendelian Inheritance in Animals (OMIA):
  a record of advances in animal genetics.* omia.org
- MHCflurry: O'Donnell et al., *Cell Systems* (2020).
  "MHCflurry 2.0: Improved Pan-Allele Prediction of MHC Class I-Presented
  Peptides by Incorporating Antigen Processing."
- pyensembl: Rubinsteyn et al. "pyensembl: Ensembl variant effect predictor
  in Python." GitHub.
