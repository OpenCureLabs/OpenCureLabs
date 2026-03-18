"""
Neoantigen prediction skill — predicts neoantigens from somatic variants and HLA typing.

Pipeline:
  1. Parse somatic variants from VCF (pysam)
  2. Look up affected transcripts and protein sequences (pyensembl)
  3. Generate mutant peptide windows (8–11mers) around each mutation
  4. Score MHC-I binding affinity via MHCflurry (no academic license required)
  5. Rank candidates by predicted IC50 (< 500 nM = strong binder)
  6. Log pipeline run to PostgreSQL
  7. Return structured NeoantigenOutput

Binding predictor: MHCflurry 2.x (CPU-based, pan-allele model).
NetMHCpan is preferred when available under academic license but requires
a manual install — MHCflurry is the default fallback.
"""

import logging
from pathlib import Path

from pydantic import BaseModel

from agentiq_labclaw.base import LabClawSkill, labclaw_skill

logger = logging.getLogger("labclaw.skills.neoantigen")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
STRONG_BINDER_IC50 = 500.0   # nM — conventional threshold
WEAK_BINDER_IC50 = 5000.0    # nM
PEPTIDE_LENGTHS = (8, 9, 10, 11)
ENSEMBL_RELEASE = 110

# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class NeoantigenInput(BaseModel):
    sample_id: str
    vcf_path: str
    hla_alleles: list[str]
    tumor_type: str


class NeoantigenCandidate(BaseModel):
    gene: str
    transcript_id: str
    variant: str              # e.g. "chr17:7674220 C>T"
    mutation: str             # e.g. "R248W"
    wildtype_peptide: str
    mutant_peptide: str
    peptide_length: int
    hla_allele: str
    ic50_mt: float            # mutant IC50 (nM)
    ic50_wt: float            # wildtype IC50 (nM)
    fold_change: float        # wt / mt — higher = more differential
    agretopicity: float       # ic50_wt / ic50_mt
    binding_category: str     # "strong" | "weak" | "non-binder"


class NeoantigenOutput(BaseModel):
    sample_id: str
    candidates: list[dict]
    top_candidate: dict
    confidence_score: float
    novel: bool
    critique_required: bool


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def _normalize_allele(allele: str) -> str:
    """Normalize HLA allele to MHCflurry format: HLA-A*02:01."""
    allele = allele.strip().replace("hla-", "HLA-").replace("HLA_", "HLA-")
    if not allele.startswith("HLA-"):
        allele = "HLA-" + allele
    return allele


def _parse_vcf_variants(vcf_path: str) -> list[dict]:
    """Parse somatic SNV/indel variants from a VCF file using pysam."""
    import pysam

    variants = []
    vcf = pysam.VariantFile(vcf_path)
    for rec in vcf:
        # Only process PASS or missing-filter variants
        if rec.filter.keys() and "PASS" not in rec.filter.keys():
            continue

        chrom = rec.contig
        pos = rec.pos          # 1-based
        ref = rec.ref
        for alt in rec.alts or []:
            if alt == "*" or alt == ".":
                continue
            variants.append({
                "chrom": chrom,
                "pos": pos,
                "ref": ref,
                "alt": alt,
                "id": rec.id or ".",
            })
    vcf.close()
    logger.info("Parsed %d somatic variants from %s", len(variants), vcf_path)
    return variants


def _get_affected_transcripts(chrom: str, pos: int, ref: str, alt: str):
    """
    Look up protein-coding transcripts overlapping a variant position.
    Returns list of (transcript, codon_index, ref_aa, alt_aa, protein_sequence).
    """
    from Bio.Data.CodonTable import standard_dna_table
    from pyensembl import EnsemblRelease

    ensembl = EnsemblRelease(ENSEMBL_RELEASE)

    # Normalize chromosome (strip 'chr' prefix if present for Ensembl)
    contig = chrom.replace("chr", "")

    results = []
    try:
        transcript_ids = ensembl.transcript_ids_at_locus(contig=contig, position=pos)
    except Exception:
        logger.debug("No transcripts found at %s:%d", chrom, pos)
        return results

    for tid in transcript_ids:
        try:
            tx = ensembl.transcript_by_id(tid)
        except Exception:  # noqa: S112
            continue

        # Only protein-coding transcripts
        if not hasattr(tx, "protein_sequence") or tx.protein_sequence is None:
            continue

        try:
            # Get CDS offset for this genomic position
            coding_offset = _genomic_to_coding_offset(tx, pos)
            if coding_offset is None:
                continue

            codon_index = coding_offset // 3
            _codon_pos_in_triplet = coding_offset % 3  # noqa: F841

            protein_seq = tx.protein_sequence
            if codon_index >= len(protein_seq):
                continue

            ref_aa = protein_seq[codon_index]

            # For SNVs, compute the mutant amino acid
            if len(ref) == 1 and len(alt) == 1:
                alt_aa = _mutate_codon(tx, coding_offset, alt, standard_dna_table)
                if alt_aa is None:
                    continue
                # Skip synonymous mutations
                if ref_aa == alt_aa:
                    continue
            else:
                # Indels — frameshift, mark but skip detailed peptide generation
                alt_aa = "fs"

            results.append({
                "transcript": tx,
                "transcript_id": tid,
                "gene": tx.gene.name if tx.gene else "unknown",
                "codon_index": codon_index,
                "ref_aa": ref_aa,
                "alt_aa": alt_aa,
                "protein_sequence": protein_seq,
            })
        except Exception as e:
            logger.debug("Error processing transcript %s: %s", tid, e)
            continue

    return results


def _genomic_to_coding_offset(transcript, genomic_pos: int) -> int | None:
    """
    Convert a 1-based genomic position to a 0-based CDS offset.
    Returns None if the position is not within a coding exon.

    Builds the full CDS-position list in transcript order (handles
    both + and − strand genes correctly).
    """
    try:
        coding_sequence = transcript.coding_sequence
        if coding_sequence is None:
            return None
    except Exception:
        return None

    if not transcript.start_codon_positions or not transcript.stop_codon_positions:
        return None

    exons = sorted(transcript.exons, key=lambda e: e.start)

    if transcript.strand == "+":
        start_pos = min(transcript.start_codon_positions)
        stop_pos = max(transcript.stop_codon_positions)
    else:
        exons = list(reversed(exons))
        start_pos = max(transcript.start_codon_positions)
        stop_pos = min(transcript.stop_codon_positions)

    cds_offset = 0
    in_cds = False

    for exon in exons:
        if transcript.strand == "+":
            positions = range(exon.start, exon.end + 1)
        else:
            positions = range(exon.end, exon.start - 1, -1)

        for gpos in positions:
            if gpos == start_pos:
                in_cds = True
            if in_cds:
                if gpos == genomic_pos:
                    return cds_offset
                cds_offset += 1
                if cds_offset >= len(coding_sequence):
                    return None
                if gpos == stop_pos:
                    return None

    return None


def _mutate_codon(transcript, coding_offset: int, alt_base: str, codon_table) -> str | None:
    """Given a CDS offset and alt base, return the mutant amino acid."""
    try:
        coding_seq = transcript.coding_sequence
        if coding_seq is None:
            return None

        codon_start = (coding_offset // 3) * 3
        if codon_start + 3 > len(coding_seq):
            return None

        codon = list(coding_seq[codon_start:codon_start + 3])
        pos_in_codon = coding_offset % 3

        # For negative strand, complement the alt base
        if transcript.strand == "-":
            complement = {"A": "T", "T": "A", "C": "G", "G": "C"}
            alt_base = complement.get(alt_base.upper(), alt_base)

        codon[pos_in_codon] = alt_base.upper()
        mutant_codon = "".join(codon)

        # Translate
        from Bio.Seq import Seq
        aa = str(Seq(mutant_codon).translate())
        return aa if aa != "*" else "Stop"
    except Exception:
        return None


def _generate_peptide_windows(
    protein_seq: str,
    codon_index: int,
    ref_aa: str,
    alt_aa: str,
    lengths: tuple[int, ...] = PEPTIDE_LENGTHS,
) -> list[tuple[str, str, int]]:
    """
    Generate wildtype and mutant peptide windows around the mutation site.
    Returns [(wt_peptide, mt_peptide, length), ...].
    """
    if alt_aa == "fs" or alt_aa == "Stop":
        return []

    mutant_seq = protein_seq[:codon_index] + alt_aa + protein_seq[codon_index + 1:]
    peptides = []

    for plen in lengths:
        # Slide a window so the mutation position is at each position within the peptide
        for offset in range(plen):
            start = codon_index - offset
            end = start + plen
            if start < 0 or end > len(protein_seq):
                continue
            wt_pep = protein_seq[start:end]
            mt_pep = mutant_seq[start:end]
            if wt_pep != mt_pep:  # Only keep windows where mutation is present
                peptides.append((wt_pep, mt_pep, plen))

    return peptides


def _predict_binding(
    alleles: list[str],
    wt_peptides: list[str],
    mt_peptides: list[str],
    predictor=None,
) -> list[tuple[str, float, float]]:
    """
    Predict MHC-I binding affinity for wildtype and mutant peptides.
    Returns [(allele, ic50_mt, ic50_wt), ...] per allele×peptide pair.
    If predictor is None, loads a new one (slow — prefer passing a cached instance).
    """
    from mhcflurry import Class1AffinityPredictor

    if predictor is None:
        predictor = Class1AffinityPredictor.load()

    supported = set(predictor.supported_alleles)

    results = []
    for allele in alleles:
        norm = _normalize_allele(allele)
        if norm not in supported:
            logger.warning("Allele %s not supported by MHCflurry, skipping", norm)
            continue

        if not mt_peptides:
            continue
        mt_ic50s = predictor.predict(
            alleles=[norm] * len(mt_peptides),
            peptides=mt_peptides,
        )
        wt_ic50s = predictor.predict(
            alleles=[norm] * len(wt_peptides),
            peptides=wt_peptides,
        )

        for i in range(len(mt_peptides)):
            results.append((norm, float(mt_ic50s[i]), float(wt_ic50s[i])))

    return results


# ---------------------------------------------------------------------------
# Skill class
# ---------------------------------------------------------------------------

@labclaw_skill(
    name="neoantigen_prediction",
    description="Predicts neoantigens from somatic variant calls and HLA typing using MHCflurry",
    input_schema=NeoantigenInput,
    output_schema=NeoantigenOutput,
    compute="local",
    gpu_required=False,
)
class NeoantigenSkill(LabClawSkill):
    """
    Full neoantigen prediction pipeline:
    1. Parse somatic variants from VCF (pysam)
    2. Look up affected transcripts and protein sequences (pyensembl / Ensembl 110)
    3. Generate mutant peptide windows (8–11mers) around each missense mutation
    4. Score MHC-I binding affinity via MHCflurry (pan-allele model)
    5. Rank candidates by IC50 — strong binders < 500 nM
    6. Log pipeline run to PostgreSQL
    7. Return top candidates as structured output
    """

    def run(self, input_data: NeoantigenInput) -> NeoantigenOutput:
        logger.info(
            "Running neoantigen prediction for sample %s (alleles: %s, tumor: %s)",
            input_data.sample_id,
            input_data.hla_alleles,
            input_data.tumor_type,
        )

        # --- Log pipeline start to DB (best-effort) ---
        pipeline_run_id = None
        try:
            from agentiq_labclaw.db.pipeline_runs import complete_pipeline, start_pipeline

            pipeline_run_id = start_pipeline(
                "neoantigen_prediction",
                input_data.model_dump(),
            )
        except Exception as e:
            logger.warning("Could not log pipeline start to DB: %s", e)

        try:
            result = self._run_pipeline(input_data)
        except Exception:
            if pipeline_run_id is not None:
                try:
                    complete_pipeline(pipeline_run_id, "failed")
                except Exception:  # noqa: S110
                    pass
            raise

        # --- Log pipeline completion ---
        if pipeline_run_id is not None:
            try:
                complete_pipeline(pipeline_run_id, "completed")
            except Exception as e:
                logger.warning("Could not log pipeline completion to DB: %s", e)

        return result

    def _run_pipeline(self, input_data: NeoantigenInput) -> NeoantigenOutput:
        from mhcflurry import Class1AffinityPredictor

        # 1. Parse VCF
        vcf_path = input_data.vcf_path
        if not Path(vcf_path).exists():
            raise FileNotFoundError(f"VCF file not found: {vcf_path}")

        variants = _parse_vcf_variants(vcf_path)
        if not variants:
            logger.info("No somatic variants found in VCF")
            return self._empty_output(input_data.sample_id)

        # Normalize HLA alleles
        alleles = [_normalize_allele(a) for a in input_data.hla_alleles]

        # Load predictor once
        predictor = Class1AffinityPredictor.load()
        supported = set(predictor.supported_alleles)
        valid_alleles = [a for a in alleles if a in supported]
        if not valid_alleles:
            logger.warning("No supported HLA alleles found")
            return self._empty_output(input_data.sample_id)

        # 2-3. Collect all unique peptide entries across variants/transcripts
        # Key: (gene, mt_peptide) → metadata dict
        peptide_entries: dict[tuple[str, str], dict] = {}

        for var in variants:
            affected = _get_affected_transcripts(
                var["chrom"], var["pos"], var["ref"], var["alt"],
            )
            for hit in affected:
                windows = _generate_peptide_windows(
                    hit["protein_sequence"],
                    hit["codon_index"],
                    hit["ref_aa"],
                    hit["alt_aa"],
                )
                for wt_pep, mt_pep, plen in windows:
                    key = (hit["gene"], mt_pep)
                    if key not in peptide_entries:
                        mutation_str = f"{hit['ref_aa']}{hit['codon_index'] + 1}{hit['alt_aa']}"
                        variant_str = f"{var['chrom']}:{var['pos']} {var['ref']}>{var['alt']}"
                        peptide_entries[key] = {
                            "gene": hit["gene"],
                            "transcript_id": hit["transcript_id"],
                            "variant": variant_str,
                            "mutation": mutation_str,
                            "wt_peptide": wt_pep,
                            "mt_peptide": mt_pep,
                            "peptide_length": plen,
                        }

        if not peptide_entries:
            logger.info("No missense peptide windows generated")
            return self._empty_output(input_data.sample_id)

        # 4. Batch-predict binding for all unique peptides × all alleles
        entries = list(peptide_entries.values())
        all_mt = [e["mt_peptide"] for e in entries]
        all_wt = [e["wt_peptide"] for e in entries]
        n = len(all_mt)

        all_candidates: list[dict] = []

        for allele in valid_alleles:
            mt_ic50s = predictor.predict(
                alleles=[allele] * n,
                peptides=all_mt,
            )
            wt_ic50s = predictor.predict(
                alleles=[allele] * n,
                peptides=all_wt,
            )

            for i, entry in enumerate(entries):
                ic50_mt = float(mt_ic50s[i])
                ic50_wt = float(wt_ic50s[i])
                fold_change = ic50_wt / ic50_mt if ic50_mt > 0 else 0.0

                if ic50_mt < STRONG_BINDER_IC50:
                    category = "strong"
                elif ic50_mt < WEAK_BINDER_IC50:
                    category = "weak"
                else:
                    category = "non-binder"

                candidate = NeoantigenCandidate(
                    gene=entry["gene"],
                    transcript_id=entry["transcript_id"],
                    variant=entry["variant"],
                    mutation=entry["mutation"],
                    wildtype_peptide=entry["wt_peptide"],
                    mutant_peptide=entry["mt_peptide"],
                    peptide_length=entry["peptide_length"],
                    hla_allele=allele,
                    ic50_mt=round(ic50_mt, 2),
                    ic50_wt=round(ic50_wt, 2),
                    fold_change=round(fold_change, 2),
                    agretopicity=round(fold_change, 2),
                    binding_category=category,
                )
                all_candidates.append(candidate.model_dump())

        # 6. Rank by IC50 (lower = stronger binder)
        all_candidates.sort(key=lambda c: c["ic50_mt"])

        # Filter to binders only for the final ranked list
        binders = [c for c in all_candidates if c["binding_category"] in ("strong", "weak")]
        strong_binders = [c for c in all_candidates if c["binding_category"] == "strong"]

        logger.info(
            "Found %d total candidates, %d binders (%d strong)",
            len(all_candidates), len(binders), len(strong_binders),
        )

        if not binders:
            return self._empty_output(input_data.sample_id)

        top = binders[0]

        # Confidence: fraction of strong binders relative to total candidates
        confidence = len(strong_binders) / max(len(all_candidates), 1)

        has_candidates = len(strong_binders) > 0

        return NeoantigenOutput(
            sample_id=input_data.sample_id,
            candidates=binders,
            top_candidate=top,
            confidence_score=round(confidence, 4),
            novel=has_candidates,
            critique_required=has_candidates,
        )

    @staticmethod
    def _empty_output(sample_id: str) -> NeoantigenOutput:
        return NeoantigenOutput(
            sample_id=sample_id,
            candidates=[],
            top_candidate={},
            confidence_score=0.0,
            novel=False,
            critique_required=False,
        )
