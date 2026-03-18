"""Variant pathogenicity scoring skill — ClinVar/OMIM cross-reference + CADD API."""

import logging

import requests
from pydantic import BaseModel

from agentiq_labclaw.base import LabClawSkill, labclaw_skill
from agentiq_labclaw.connectors.clinvar import ClinVarConnector

logger = logging.getLogger("labclaw.skills.variant_pathogenicity")

CADD_API = "https://cadd.gs.washington.edu/api/v1.0"

# ACMG-style classification thresholds
CADD_PATHOGENIC_THRESHOLD = 25.0
CADD_LIKELY_PATHOGENIC_THRESHOLD = 20.0
CADD_LIKELY_BENIGN_THRESHOLD = 10.0


class VariantInput(BaseModel):
    variant_id: str  # e.g. "chr17:7674220:C>T"
    gene: str
    transcript: str | None = None
    hgvs: str | None = None


class VariantOutput(BaseModel):
    variant_id: str
    gene: str
    clinvar_significance: str | None
    omim_associations: list[dict]
    pathogenicity_score: float
    classification: str  # "pathogenic" | "likely_pathogenic" | "vus" | "likely_benign" | "benign"
    novel: bool
    critique_required: bool


def _query_cadd(chrom: str, pos: int, ref: str, alt: str) -> float | None:
    """Query CADD API for a variant's PHRED-scaled score."""
    try:
        # CADD API format: /score/GRCh38/chr:pos:ref:alt
        url = f"{CADD_API}/score/GRCh38/{chrom}:{pos}:{ref}:{alt}"
        resp = requests.get(url, timeout=30)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        data = resp.json()
        # Return PHRED-scaled CADD score
        if isinstance(data, list) and data:
            return float(data[-1].get("PHRED", 0))
        return None
    except Exception as e:
        logger.warning("CADD query failed for %s:%d %s>%s: %s", chrom, pos, ref, alt, e)
        return None


def _parse_variant_id(variant_id: str) -> tuple[str, int, str, str] | None:
    """Parse 'chr17:7674220:C>T' or 'chr17:7674220 C>T' into (chrom, pos, ref, alt)."""
    vid = variant_id.replace(" ", ":").replace(">", ":")
    parts = [p for p in vid.split(":") if p]
    if len(parts) >= 4:
        try:
            return parts[0], int(parts[1]), parts[2], parts[3]
        except (ValueError, IndexError):
            pass
    return None


def _classify(cadd_score: float | None, clinvar_sig: str | None) -> tuple[str, float]:
    """Classify pathogenicity based on CADD score and ClinVar significance."""
    # ClinVar takes priority if available
    if clinvar_sig:
        sig_lower = clinvar_sig.lower()
        if "pathogenic" in sig_lower and "likely" not in sig_lower:
            return "pathogenic", 1.0
        if "likely pathogenic" in sig_lower or "likely_pathogenic" in sig_lower:
            return "likely_pathogenic", 0.8
        if "benign" in sig_lower and "likely" not in sig_lower:
            return "benign", 0.0
        if "likely benign" in sig_lower or "likely_benign" in sig_lower:
            return "likely_benign", 0.1

    # Fall back to CADD score
    if cadd_score is not None:
        if cadd_score >= CADD_PATHOGENIC_THRESHOLD:
            return "pathogenic", round(cadd_score / 40.0, 4)
        if cadd_score >= CADD_LIKELY_PATHOGENIC_THRESHOLD:
            return "likely_pathogenic", round(cadd_score / 40.0, 4)
        if cadd_score <= CADD_LIKELY_BENIGN_THRESHOLD:
            return "likely_benign", round(cadd_score / 40.0, 4)

    return "vus", 0.5


@labclaw_skill(
    name="variant_pathogenicity",
    description="Scores variant pathogenicity by cross-referencing ClinVar and OMIM databases",
    input_schema=VariantInput,
    output_schema=VariantOutput,
    compute="local",
    gpu_required=False,
)
class VariantPathogenicitySkill(LabClawSkill):
    """
    Pipeline:
    1. Query ClinVar for existing classifications
    2. Query OMIM/MedGen for gene-disease associations
    3. Query CADD API for computational pathogenicity score
    4. Aggregate scores and classify (ACMG-style)
    """

    def run(self, input_data: VariantInput) -> VariantOutput:
        logger.info("Scoring pathogenicity for %s in %s", input_data.variant_id, input_data.gene)

        clinvar = ClinVarConnector()

        # 1. ClinVar lookup
        clinvar_sig = None
        lookup_term = input_data.hgvs or input_data.variant_id
        cv_result = clinvar.lookup_variant(lookup_term)
        if cv_result:
            clinvar_sig = cv_result.get("clinical_significance")

        # 2. OMIM/MedGen associations
        omim_assoc = clinvar.lookup_omim(input_data.gene)

        # 3. CADD score
        cadd_score = None
        parsed = _parse_variant_id(input_data.variant_id)
        if parsed:
            chrom, pos, ref, alt = parsed
            cadd_score = _query_cadd(chrom, pos, ref, alt)

        # 4. Classify
        classification, score = _classify(cadd_score, clinvar_sig)

        # Adjust score if CADD is available and ClinVar gave the classification
        if cadd_score is not None and clinvar_sig:
            score = max(score, round(cadd_score / 40.0, 4))

        is_novel = clinvar_sig is None and classification in ("pathogenic", "likely_pathogenic")

        logger.info(
            "Variant %s classified as %s (score=%.4f, ClinVar=%s, CADD=%s)",
            input_data.variant_id, classification, score, clinvar_sig, cadd_score,
        )

        return VariantOutput(
            variant_id=input_data.variant_id,
            gene=input_data.gene,
            clinvar_significance=clinvar_sig,
            omim_associations=omim_assoc,
            pathogenicity_score=round(score, 4),
            classification=classification,
            novel=is_novel,
            critique_required=classification in ("pathogenic", "likely_pathogenic", "vus"),
        )
