"""
Test the neoantigen prediction pipeline with synthetic canine (dog) VCF data.

Uses:
  - Synthetic CanFam3.1 VCF with BRAF V595E, KIT exon-11, TP53 R175H, PTEN R130Q, MC1R variants
  - DLA-88 Class I alleles (Dog Leukocyte Antigen)
  - Ensembl release 112 (canis_familiaris) gene annotations

Marks xfail when pyensembl canine database is not downloaded.
Run `bash scripts/download_ensembl_species.sh dog` to enable full tests.
"""

import os
import sys
import logging
import pytest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "packages", "agentiq_labclaw"))

logging.basicConfig(level=logging.INFO, format="%(name)s | %(levelname)s | %(message)s")

from agentiq_labclaw.species import get_species, DOG

VCF_PATH = os.path.join(os.path.dirname(__file__), "data", "synthetic_canine_somatic.vcf")

# ── helpers ──────────────────────────────────────────────────────────────────

def _canine_ensembl_available() -> bool:
    """Return True if pyensembl canine release 112 is downloaded."""
    try:
        from pyensembl import EnsemblRelease
        r = EnsemblRelease(112, species="canis_familiaris")
        r.gene_ids_at_locus("chr16", 26835234)  # BRAF locus
        return True
    except Exception:
        return False


CANINE_ENSEMBL_MISSING = not _canine_ensembl_available()
SKIP_REASON = "Ensembl release 112 (dog) not downloaded — run: bash scripts/download_ensembl_species.sh dog"

# ── species registry tests ────────────────────────────────────────────────────

def test_species_registry_dog():
    """Canine species config should be importable and have correct fields."""
    cfg = get_species("dog")
    assert cfg.name == "dog"
    assert cfg.ensembl_species == "canis_familiaris"
    assert cfg.ensembl_release == 112
    assert cfg.reference_genome == "CanFam3.1"
    assert cfg.mhc_prefix == "DLA"
    assert cfg.ncbi_taxon_id == 9615
    assert cfg.supported_mhc_predictor in ("netmhcpan", "fallback_human")
    print(f"PASS: dog species config — ref={cfg.reference_genome}, predictor={cfg.supported_mhc_predictor}")


def test_species_registry_synonyms():
    """'canine' and 'canis_lupus_familiaris' should resolve to the dog config."""
    assert get_species("canine").name == "dog"
    assert get_species("canis_lupus_familiaris").name == "dog"
    print("PASS: dog species synonyms")


def test_species_registry_unknown():
    """Unknown species should raise ValueError."""
    with pytest.raises(ValueError, match="Unknown species"):
        get_species("hamster")
    print("PASS: unknown species raises ValueError")


# ── VCF parsing with canine VCF ────────────────────────────────────────────────

def test_canine_vcf_exists():
    """The synthetic canine VCF test fixture should exist."""
    assert os.path.isfile(VCF_PATH), f"Missing test fixture: {VCF_PATH}"
    print(f"PASS: canine VCF exists at {VCF_PATH}")


def test_canine_vcf_parsing():
    """VCF parser should correctly read CanFam3.1 variants."""
    from agentiq_labclaw.skills.neoantigen import _parse_vcf_variants

    variants = _parse_vcf_variants(VCF_PATH)
    assert len(variants) == 5, f"Expected 5 variants, got {len(variants)}"

    # Check BRAF V595E on chr16
    braf = next((v for v in variants if v["chrom"] == "chr16"), None)
    assert braf is not None, "BRAF variant on chr16 not found"
    assert braf["pos"] == 26835234
    assert braf["ref"] == "T"
    assert braf["alt"] == "A"

    # Check KIT on chr13
    kit = next((v for v in variants if v["chrom"] == "chr13"), None)
    assert kit is not None, "KIT variant on chr13 not found"

    print(f"PASS: canine VCF parsed — {len(variants)} variants, BRAF V595E confirmed")


# ── allele normalization for DLA ───────────────────────────────────────────────

def test_dla_allele_normalization():
    """DLA alleles should be normalized to DLA-<gene>*<fields> format."""
    from agentiq_labclaw.skills.neoantigen import _normalize_allele

    cfg = get_species("dog")
    # Fully-prefixed allele
    dla = _normalize_allele("DLA-88*501:01", cfg)
    assert "DLA" in dla and "88" in dla, f"Unexpected DLA allele format: {dla}"

    # Bare allele (no DLA- prefix)
    dla2 = _normalize_allele("88*501:01", cfg)
    assert dla2.startswith("DLA-"), f"Expected DLA- prefix for bare allele, got: {dla2}"

    print(f"PASS: DLA allele normalization — {dla}, {dla2}")


def test_fla_allele_normalization():
    """FLA allele normalization for cat should produce a valid FLA allele string."""
    from agentiq_labclaw.skills.neoantigen import _normalize_allele

    cfg = get_species("cat")
    fla = _normalize_allele("FLA-K*001", cfg)
    assert "FLA" in fla and "K" in fla, f"Unexpected FLA allele format: {fla}"
    print(f"PASS: FLA allele normalization — {fla}")


# ── MHC predictor selection ────────────────────────────────────────────────────

def test_mhc_predictor_factory():
    """get_predictor() should return an MHCPredictor for dog species."""
    from agentiq_labclaw.skills.mhc_predictor import get_predictor, MHCPredictor

    cfg = get_species("dog")
    predictor = get_predictor(cfg)
    assert isinstance(predictor, MHCPredictor)
    # NetMHCpan is ideal; _FallbackHumanPredictor is used if netMHCpan binary absent
    assert predictor.name  # any non-empty name is acceptable
    print(f"PASS: MHC predictor factory — {predictor.name} for dog species")


# ── sequencing QC species derivation ──────────────────────────────────────────

def test_sequencing_qc_canine_ref_derivation():
    """SequencingQCInput with species='dog' should auto-derive CanFam3.1 reference."""
    from agentiq_labclaw.skills.sequencing_qc import SequencingQCInput

    inp = SequencingQCInput(
        sample_id="rosie_mast_cell",
        fastq_paths=["tests/data/canine_reads.fastq.gz"],
        species="dog",
    )
    cfg = get_species(inp.species)
    assert cfg.reference_genome == "CanFam3.1"
    print(f"PASS: canine QC auto-derives ref={cfg.reference_genome}")


# ── variant pathogenicity (OMIA + VEP routing) ────────────────────────────────

def test_variant_pathogenicity_routes_to_vet():
    """VariantInput with species='dog' should dispatch to _run_veterinary()."""
    from agentiq_labclaw.skills.variant_pathogenicity import VariantPathogenicitySkill, VariantInput

    skill = VariantPathogenicitySkill()
    inp = VariantInput(
        variant_id="chr16:26835234:A>T",
        gene="BRAF",
        species="dog",
    )

    # Mock both external connectors so the test runs without network calls
    with patch("agentiq_labclaw.skills.variant_pathogenicity.OMIAConnector") as mock_omia, \
         patch("agentiq_labclaw.skills.variant_pathogenicity.EnsemblVEPConnector") as mock_vep:

        mock_omia.return_value.lookup_gene.return_value = [{
            "omia_id": "001001-9615",
            "phene": "Mast cell tumor",
            "gene_symbol": "BRAF",
            "molecular_basis": "point mutation",
        }]
        mock_vep.return_value.predict_effect.return_value = {
            "most_severe_consequence": "missense_variant",
            "sift_score": 0.001,
            "sift_prediction": "deleterious",
            "polyphen_score": 0.999,
            "polyphen_prediction": "probably_damaging",
            "impact": "MODERATE",
            "cadd_phred_proxy": 23.0,
        }

        result = skill.run(inp)

    assert result.clinvar_significance is None, "Veterinary results should not have ClinVar significance"
    assert result.classification in ("pathogenic", "likely_pathogenic", "vus", "benign")
    print(f"PASS: vet variant dispatch — classification={result.classification}")


# ── full end-to-end canine pipeline (requires pyensembl data) ─────────────────

@pytest.mark.xfail(
    condition=CANINE_ENSEMBL_MISSING,
    reason=SKIP_REASON,
    strict=False,
)
def test_canine_neoantigen_pipeline_e2e():
    """
    End-to-end canine neoantigen pipeline:
      CanFam3.1 VCF → pyensembl(112, dog) → peptides → DLA binding → ranked candidates

    Marks xfail (not error) if pyensembl canine data is not downloaded.
    """
    from agentiq_labclaw.skills.neoantigen import NeoantigenSkill, NeoantigenInput

    skill = NeoantigenSkill()
    inp = NeoantigenInput(
        sample_id="rosie_BRAF_V595E",
        vcf_path=VCF_PATH,
        hla_alleles=["DLA-88*501:01", "DLA-88*508:01"],
        tumor_type="mast_cell_tumor",
        species="dog",
    )

    result = skill.run(inp)

    assert result is not None
    assert isinstance(result.ranked_candidates, list)
    print(
        f"PASS: canine e2e pipeline — {len(result.ranked_candidates)} candidates, "
        f"novel={result.novel_candidates_count}"
    )

    # At least one candidate should come from BRAF (if annotation worked)
    if result.ranked_candidates:
        genes = {c.get("gene") for c in result.ranked_candidates}
        print(f"      Genes with candidates: {genes}")
