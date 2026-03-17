"""
Test the neoantigen prediction pipeline with synthetic VCF data.

Uses:
- A synthetic VCF with known TP53 and KRAS variants
- Common HLA-A alleles for MHC-I binding predictions
- Ensembl release 110 (GRCh38) gene annotations
"""

import os
import sys
import json
import logging

# Ensure the package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "packages", "agentiq_labclaw"))

logging.basicConfig(level=logging.INFO, format="%(name)s | %(levelname)s | %(message)s")

from agentiq_labclaw.skills.neoantigen import (
    NeoantigenInput,
    NeoantigenSkill,
    _parse_vcf_variants,
    _normalize_allele,
)


def test_allele_normalization():
    """Test HLA allele string normalization."""
    assert _normalize_allele("A*02:01") == "HLA-A*02:01"
    assert _normalize_allele("HLA-A*02:01") == "HLA-A*02:01"
    assert _normalize_allele("hla-B*07:02") == "HLA-B*07:02"
    print("PASS: allele normalization")


def test_vcf_parsing():
    """Test VCF variant parsing."""
    vcf_path = os.path.join(os.path.dirname(__file__), "data", "synthetic_somatic.vcf")
    variants = _parse_vcf_variants(vcf_path)
    assert len(variants) == 2, f"Expected 2 variants, got {len(variants)}"
    assert variants[0]["chrom"] == "17"
    assert variants[0]["pos"] == 7675088
    assert variants[0]["ref"] == "C"
    assert variants[0]["alt"] == "T"
    assert variants[1]["chrom"] == "12"
    print(f"PASS: VCF parsing — {len(variants)} variants")


def test_full_pipeline():
    """Run the full neoantigen prediction pipeline on synthetic data."""
    vcf_path = os.path.join(os.path.dirname(__file__), "data", "synthetic_somatic.vcf")

    inp = NeoantigenInput(
        sample_id="TEST_001",
        vcf_path=vcf_path,
        hla_alleles=["HLA-A*02:01", "HLA-A*03:01", "HLA-B*07:02"],
        tumor_type="NSCLC",
    )

    skill = NeoantigenSkill()
    result = skill.run(inp)

    print(f"\n{'='*60}")
    print(f"Sample: {result.sample_id}")
    print(f"Total candidates (binders): {len(result.candidates)}")
    print(f"Confidence score: {result.confidence_score}")
    print(f"Novel: {result.novel}")
    print(f"Critique required: {result.critique_required}")

    if result.candidates:
        print(f"\nTop candidate:")
        top = result.top_candidate
        print(f"  Gene: {top.get('gene')}")
        print(f"  Mutation: {top.get('mutation')}")
        print(f"  Mutant peptide: {top.get('mutant_peptide')}")
        print(f"  HLA allele: {top.get('hla_allele')}")
        print(f"  IC50 (mutant): {top.get('ic50_mt')} nM")
        print(f"  IC50 (wildtype): {top.get('ic50_wt')} nM")
        print(f"  Binding category: {top.get('binding_category')}")
        print(f"  Fold change: {top.get('fold_change')}")

        print(f"\nAll strong binders:")
        for c in result.candidates:
            if c["binding_category"] == "strong":
                print(f"  {c['gene']} {c['mutation']} | {c['mutant_peptide']} | "
                      f"{c['hla_allele']} | IC50={c['ic50_mt']} nM")

    print(f"{'='*60}")
    print(f"\nFull output JSON:")
    print(json.dumps(result.model_dump(), indent=2, default=str))

    # Basic assertions
    assert result.sample_id == "TEST_001"
    assert isinstance(result.candidates, list)
    assert isinstance(result.confidence_score, float)
    print("\nPASS: full pipeline")


if __name__ == "__main__":
    test_allele_normalization()
    test_vcf_parsing()
    test_full_pipeline()
    print("\nAll tests passed.")
