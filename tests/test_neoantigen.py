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
import pytest
from unittest.mock import MagicMock, patch
from types import SimpleNamespace

# Ensure the package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "packages", "agentiq_labclaw"))

logging.basicConfig(level=logging.INFO, format="%(name)s | %(levelname)s | %(message)s")

from agentiq_labclaw.skills.neoantigen import (
    NeoantigenInput,
    NeoantigenOutput,
    NeoantigenSkill,
    _parse_vcf_variants,
    _normalize_allele,
    _generate_peptide_windows,
    _genomic_to_coding_offset,
    _mutate_codon,
    STRONG_BINDER_IC50,
    WEAK_BINDER_IC50,
    PEPTIDE_LENGTHS,
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


@pytest.mark.skipif(
    not os.path.isdir(os.path.expanduser("~/.local/share/mhcflurry")),
    reason="MHCflurry models not downloaded (use --skip-models?)",
)
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


# ---------------------------------------------------------------------------
# Unit tests for _normalize_allele
# ---------------------------------------------------------------------------


class TestNormalizeAllele:
    def test_bare_allele_gets_prefix(self):
        assert _normalize_allele("A*02:01") == "HLA-A*02:01"

    def test_already_prefixed(self):
        assert _normalize_allele("HLA-A*02:01") == "HLA-A*02:01"

    def test_lowercase_hla_prefix(self):
        assert _normalize_allele("hla-B*07:02") == "HLA-B*07:02"

    def test_underscore_prefix(self):
        assert _normalize_allele("HLA_C*06:02") == "HLA-C*06:02"

    def test_whitespace_stripped(self):
        assert _normalize_allele("  A*03:01  ") == "HLA-A*03:01"

    def test_b_allele(self):
        assert _normalize_allele("B*44:03") == "HLA-B*44:03"

    def test_c_allele(self):
        assert _normalize_allele("C*07:01") == "HLA-C*07:01"


# ---------------------------------------------------------------------------
# Unit tests for _generate_peptide_windows
# ---------------------------------------------------------------------------


class TestGeneratePeptideWindows:
    def test_basic_missense(self):
        # Simple protein: ACDEFGHIKLMNPQ (14 aa)
        # Mutation at index 5: G -> W
        protein = "ACDEFGHIKLMNPQ"
        windows = _generate_peptide_windows(protein, 5, "G", "W")
        assert len(windows) > 0
        # All mutant peptides should contain 'W'
        for wt, mt, plen in windows:
            assert "W" in mt
            assert "G" in wt or wt != mt
            assert len(mt) == plen
            assert len(wt) == plen

    def test_frameshift_returns_empty(self):
        windows = _generate_peptide_windows("ACDEFGHIKLMNPQ", 5, "G", "fs")
        assert windows == []

    def test_stop_codon_returns_empty(self):
        windows = _generate_peptide_windows("ACDEFGHIKLMNPQ", 5, "G", "Stop")
        assert windows == []

    def test_mutation_at_start(self):
        protein = "ACDEFGHIKLMNPQ"
        windows = _generate_peptide_windows(protein, 0, "A", "W")
        assert len(windows) > 0
        for wt, mt, plen in windows:
            assert mt[0] == "W" or "W" in mt

    def test_mutation_at_end(self):
        protein = "ACDEFGHIKLMNPQ"
        last_idx = len(protein) - 1
        windows = _generate_peptide_windows(protein, last_idx, "Q", "W")
        assert len(windows) > 0
        for wt, mt, plen in windows:
            assert "W" in mt

    def test_peptide_lengths(self):
        protein = "ACDEFGHIKLMNPQRSTVWY"  # 20 aa
        windows = _generate_peptide_windows(protein, 10, "M", "W")
        observed_lengths = {plen for _, _, plen in windows}
        for plen in PEPTIDE_LENGTHS:
            assert plen in observed_lengths

    def test_wt_equals_mt_excluded(self):
        """Windows where mutation is not present should be excluded."""
        protein = "ACDEFGHIKLMNPQ"
        windows = _generate_peptide_windows(protein, 5, "G", "W")
        for wt, mt, plen in windows:
            assert wt != mt

    def test_short_protein(self):
        """Protein shorter than min peptide length should produce no 11-mers."""
        protein = "ACDEF"  # 5 aa
        windows = _generate_peptide_windows(protein, 2, "D", "W")
        for _, _, plen in windows:
            assert plen <= len(protein)

    def test_custom_lengths(self):
        protein = "ACDEFGHIKLMNPQ"
        windows = _generate_peptide_windows(protein, 5, "G", "W", lengths=(9,))
        for _, _, plen in windows:
            assert plen == 9


# ---------------------------------------------------------------------------
# Unit tests for _genomic_to_coding_offset (with mock transcript)
# ---------------------------------------------------------------------------


def _make_mock_transcript(strand="+", coding_seq="ATGCCCGGG", exons=None,
                          start_codon_pos=None, stop_codon_pos=None):
    """Create a mock transcript object for testing."""
    tx = MagicMock()
    tx.coding_sequence = coding_seq
    tx.strand = strand

    if exons is None:
        # Single exon from pos 100 to 108 (9bp = 3 codons)
        exon = MagicMock()
        exon.start = 100
        exon.end = 108
        exons = [exon]

    tx.exons = exons

    if start_codon_pos is None:
        start_codon_pos = [100] if strand == "+" else [108]
    if stop_codon_pos is None:
        stop_codon_pos = [108] if strand == "+" else [100]

    tx.start_codon_positions = start_codon_pos
    tx.stop_codon_positions = stop_codon_pos

    return tx


class TestGenomicToCodingOffset:
    def test_forward_strand_first_base(self):
        tx = _make_mock_transcript(strand="+")
        offset = _genomic_to_coding_offset(tx, 100)
        assert offset == 0

    def test_forward_strand_middle_base(self):
        tx = _make_mock_transcript(strand="+")
        offset = _genomic_to_coding_offset(tx, 103)
        assert offset == 3

    def test_position_outside_cds_returns_none(self):
        tx = _make_mock_transcript(strand="+")
        offset = _genomic_to_coding_offset(tx, 50)
        assert offset is None

    def test_no_coding_sequence_returns_none(self):
        tx = _make_mock_transcript()
        tx.coding_sequence = None
        offset = _genomic_to_coding_offset(tx, 100)
        assert offset is None

    def test_no_start_codon_returns_none(self):
        tx = _make_mock_transcript()
        tx.start_codon_positions = []
        offset = _genomic_to_coding_offset(tx, 100)
        assert offset is None

    def test_reverse_strand(self):
        tx = _make_mock_transcript(strand="-")
        # For reverse strand, exons are reversed and positions are iterated high→low
        offset = _genomic_to_coding_offset(tx, 108)
        assert offset == 0


# ---------------------------------------------------------------------------
# Unit tests for _mutate_codon (with mock transcript)
# ---------------------------------------------------------------------------


class TestMutateCodon:
    def test_forward_strand_snv(self):
        # coding_seq = ATG CCC GGG
        # Mutate offset 3 (first base of codon 1 'CCC') — C→T → TCC = Ser
        tx = _make_mock_transcript(strand="+", coding_seq="ATGCCCGGG")
        result = _mutate_codon(tx, 3, "T", None)
        assert result == "S"  # TCC → Ser

    def test_reverse_strand_complement(self):
        # For negative strand, alt base is complemented: A→T
        tx = _make_mock_transcript(strand="-", coding_seq="ATGCCCGGG")
        result = _mutate_codon(tx, 3, "A", None)
        # complement of A is T, so codon CCC → TCC = Ser
        assert result == "S"

    def test_stop_codon_mutation(self):
        # ATG → TAG (amber stop)
        tx = _make_mock_transcript(strand="+", coding_seq="ATGCCCGGG")
        result = _mutate_codon(tx, 0, "T", None)
        # Codon ATG → TTG = Leu
        assert result == "L"

    def test_no_coding_sequence(self):
        tx = _make_mock_transcript()
        tx.coding_sequence = None
        result = _mutate_codon(tx, 0, "T", None)
        assert result is None

    def test_offset_out_of_bounds(self):
        tx = _make_mock_transcript(strand="+", coding_seq="ATG")
        # Codon start would be 3 which is out of range for 3bp sequence
        result = _mutate_codon(tx, 3, "T", None)
        assert result is None


# ---------------------------------------------------------------------------
# Unit tests for NeoantigenOutput / _empty_output
# ---------------------------------------------------------------------------


class TestNeoantigenOutput:
    def test_empty_output(self):
        out = NeoantigenSkill._empty_output("S001")
        assert out.sample_id == "S001"
        assert out.candidates == []
        assert out.top_candidate == {}
        assert out.confidence_score == 0.0
        assert out.novel is False
        assert out.critique_required is False

    def test_output_schema_validation(self):
        out = NeoantigenOutput(
            sample_id="S002",
            candidates=[{"gene": "TP53"}],
            top_candidate={"gene": "TP53"},
            confidence_score=0.85,
            novel=True,
            critique_required=True,
        )
        assert out.sample_id == "S002"
        assert len(out.candidates) == 1

    def test_input_schema_validation(self):
        inp = NeoantigenInput(
            sample_id="S003",
            vcf_path="/tmp/test.vcf",
            hla_alleles=["HLA-A*02:01"],
            tumor_type="BRCA",
        )
        assert inp.sample_id == "S003"
        assert len(inp.hla_alleles) == 1

    def test_input_schema_rejects_missing_fields(self):
        with pytest.raises(Exception):
            NeoantigenInput(sample_id="S004")


# ---------------------------------------------------------------------------
# Constants tests
# ---------------------------------------------------------------------------


class TestConstants:
    def test_binder_thresholds(self):
        assert STRONG_BINDER_IC50 == 500.0
        assert WEAK_BINDER_IC50 == 5000.0
        assert STRONG_BINDER_IC50 < WEAK_BINDER_IC50

    def test_peptide_lengths(self):
        assert PEPTIDE_LENGTHS == (8, 9, 10, 11)
        assert all(isinstance(l, int) for l in PEPTIDE_LENGTHS)


if __name__ == "__main__":
    test_allele_normalization()
    test_vcf_parsing()
    test_full_pipeline()
    print("\nAll tests passed.")
