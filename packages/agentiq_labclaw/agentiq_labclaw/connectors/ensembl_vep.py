"""
Ensembl VEP (Variant Effect Predictor) REST API connector.

Provides species-agnostic variant effect prediction using SIFT and PolyPhen2
scores.  Replaces the CADD API for non-human species (CADD is GRCh38-only).

API docs: https://rest.ensembl.org/#VEP (open access, no auth required)

Usage:
    from agentiq_labclaw.connectors.ensembl_vep import EnsemblVEPConnector
    conn = EnsemblVEPConnector()
    result = conn.predict_effect(
        chrom="chr7", pos=140453136, ref="A", alt="T",
        species="canis_lupus_familiaris",
    )
"""

from __future__ import annotations

import logging

import requests

logger = logging.getLogger("labclaw.connectors.ensembl_vep")

ENSEMBL_REST = "https://rest.ensembl.org"
DEFAULT_TIMEOUT = 30


class EnsemblVEPConnector:
    """
    Client for the Ensembl VEP REST API.

    Supports all Ensembl species — used for variant pathogenicity scoring
    in non-human pipelines (dog, cat, and any other Ensembl species).
    """

    def __init__(self, timeout: int = DEFAULT_TIMEOUT) -> None:
        self._timeout = timeout
        self._session = requests.Session()
        self._session.headers.update({
            "Content-Type": "application/json",
            "Accept": "application/json",
        })

    def predict_effect(
        self,
        chrom: str,
        pos: int,
        ref: str,
        alt: str,
        species: str = "homo_sapiens",
    ) -> dict:
        """
        Predict variant effect via Ensembl VEP for any supported species.

        Args:
            chrom: Chromosome (with or without 'chr' prefix).
            pos:   1-based genomic position.
            ref:   Reference allele.
            alt:   Alternate allele.
            species: Ensembl species string (e.g. "canis_lupus_familiaris").

        Returns:
            Dict with keys: sift_score, sift_prediction, polyphen_score,
            polyphen_prediction, consequence, most_severe_consequence,
            gene_id, transcript_id, impact.
            Returns an empty-results dict on failure.
        """
        chrom_clean = chrom.replace("chr", "")
        # Ensembl VEP HGVS-style region notation
        variant_str = f"{chrom_clean}:{pos} {pos} 1 {ref}/{alt}"

        try:
            url = f"{ENSEMBL_REST}/vep/{species}/region/{chrom_clean}:{pos}-{pos}/{alt}"
            resp = self._session.get(
                url,
                params={"SIFT": "b", "PolyPhen": "b", "canonical": "1"},
                timeout=self._timeout,
            )
            if resp.status_code == 400:
                logger.debug(
                    "VEP returned 400 for %s:%d %s>%s (%s) — variant outside annotation",
                    chrom, pos, ref, alt, species,
                )
                return self._empty_result()
            if resp.status_code == 404:
                return self._empty_result()
            resp.raise_for_status()

            data = resp.json()
            if not data:
                return self._empty_result()

            return self._parse_response(data[0])

        except requests.exceptions.ConnectionError:
            logger.warning("Ensembl REST unreachable — skipping VEP prediction")
            return self._empty_result()
        except Exception as exc:
            logger.warning(
                "VEP prediction failed for %s:%d %s>%s: %s",
                chrom, pos, ref, alt, exc,
            )
            return self._empty_result()

    def _parse_response(self, entry: dict) -> dict:
        """Extract SIFT, PolyPhen, consequence from first VEP result entry."""
        most_severe = entry.get("most_severe_consequence", "")

        sift_score: float | None = None
        sift_prediction = ""
        polyphen_score: float | None = None
        polyphen_prediction = ""
        gene_id = ""
        transcript_id = ""
        impact = "MODIFIER"

        # Walk transcript consequences to find canonical
        for tc in entry.get("transcript_consequences", []):
            if tc.get("canonical") != 1:
                continue
            gene_id = tc.get("gene_id", "")
            transcript_id = tc.get("transcript_id", "")
            impact = tc.get("impact", impact)
            if "sift_score" in tc:
                sift_score = tc["sift_score"]
                sift_prediction = tc.get("sift_prediction", "")
            if "polyphen_score" in tc:
                polyphen_score = tc["polyphen_score"]
                polyphen_prediction = tc.get("polyphen_prediction", "")
            break

        return {
            "sift_score": sift_score,
            "sift_prediction": sift_prediction,
            "polyphen_score": polyphen_score,
            "polyphen_prediction": polyphen_prediction,
            "most_severe_consequence": most_severe,
            "impact": impact,
            "gene_id": gene_id,
            "transcript_id": transcript_id,
            "source": "Ensembl_VEP",
        }

    @staticmethod
    def _empty_result() -> dict:
        return {
            "sift_score": None,
            "sift_prediction": "",
            "polyphen_score": None,
            "polyphen_prediction": "",
            "most_severe_consequence": "",
            "impact": "MODIFIER",
            "gene_id": "",
            "transcript_id": "",
            "source": "Ensembl_VEP",
        }

    def phred_from_sift(self, sift_score: float | None) -> float | None:
        """
        Convert SIFT score to a rough CADD-PHRED-equivalent for the classifier.

        SIFT < 0.05 → deleterious → ~PHRED 25+
        SIFT 0.05–0.2 → possibly deleterious → ~PHRED 15-25
        SIFT > 0.2 → tolerated → < PHRED 15
        """
        if sift_score is None:
            return None
        if sift_score < 0.05:
            return 25.0 + (0.05 - sift_score) * 200  # cap at ~35
        if sift_score < 0.2:
            return 15.0 + (0.2 - sift_score) / 0.15 * 10
        return max(0.0, 15.0 - sift_score * 50)
