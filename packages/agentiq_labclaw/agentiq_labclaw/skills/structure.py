"""Protein structure prediction skill — ESMFold / AlphaFold integration."""

import logging
import time
from pathlib import Path

import requests
from pydantic import BaseModel

from agentiq_labclaw.base import LabClawSkill, labclaw_skill

logger = logging.getLogger("labclaw.skills.structure")

REPORTS_DIR = Path("/root/opencurelabs/reports/structures")
ESMFOLD_API = "https://api.esmatlas.com/foldSequence/v1/pdb/"
ALPHAFOLD_API = "https://alphafold.ebi.ac.uk/api"
UNIPROT_API = "https://rest.uniprot.org/uniprotkb/search"


class StructureInput(BaseModel):
    protein_id: str
    sequence: str
    method: str = "esmfold"  # "esmfold" | "alphafold"


class StructureOutput(BaseModel):
    protein_id: str
    pdb_path: str
    confidence_score: float
    method_used: str
    novel: bool
    critique_required: bool


@labclaw_skill(
    name="structure_prediction",
    description="Predicts protein 3D structure from amino acid sequence using ESMFold or AlphaFold",
    input_schema=StructureInput,
    output_schema=StructureOutput,
    compute="local",
    gpu_required=True,
)
class StructurePredictionSkill(LabClawSkill):
    """
    Pipeline:
    1. Validate input sequence
    2. Run structure prediction (ESMFold API or AlphaFold DB lookup)
    3. Score confidence (pLDDT)
    4. Save PDB output
    """

    def run(self, input_data: StructureInput) -> StructureOutput:
        logger.info("Predicting structure for %s via %s", input_data.protein_id, input_data.method)

        REPORTS_DIR.mkdir(parents=True, exist_ok=True)

        # Auto-resolve placeholder sequences from UniProt
        seq = input_data.sequence.strip().upper()
        accession = None
        if not seq or "PLACEHOLDER" in seq or seq == "AUTO_RESOLVE":
            seq, accession = self._fetch_uniprot_sequence(input_data.protein_id)
            if not seq:
                raise ValueError(f"Could not resolve sequence for {input_data.protein_id}")

        # Replace sequence with resolved one
        resolved = input_data.model_copy(update={"sequence": seq})

        if resolved.method == "alphafold":
            return self._run_alphafold(resolved, accession=accession)
        return self._run_esmfold_with_fallback(resolved, accession=accession)

    @staticmethod
    def _fetch_uniprot_sequence(protein_id: str) -> tuple[str | None, str | None]:
        """Look up protein sequence and accession from UniProt by gene name."""
        try:
            resp = requests.get(
                UNIPROT_API,
                params={
                    "query": f"(gene:{protein_id}) AND (organism_id:9606)",
                    "format": "json",
                    "size": "1",
                    "fields": "accession,sequence",
                },
                timeout=30,
            )
            resp.raise_for_status()
            results = resp.json().get("results", [])
            if results:
                entry = results[0]
                seq = entry.get("sequence", {}).get("value")
                accession = entry.get("primaryAccession")
                if seq:
                    logger.info(
                        "Resolved %s → %s (%d aa)",
                        protein_id, accession, len(seq),
                    )
                    return seq, accession
        except Exception as exc:
            logger.warning("UniProt lookup failed for %s: %s", protein_id, exc)
        return None, None

    def _run_esmfold_with_fallback(
        self, input_data: StructureInput, *, accession: str | None = None,
    ) -> StructureOutput:
        """Try ESMFold with retry, then fall back to AlphaFold DB lookup."""
        for attempt in range(3):
            try:
                return self._run_esmfold(input_data)
            except requests.HTTPError as exc:
                if exc.response is not None and exc.response.status_code == 429:
                    wait = 2 ** attempt * 5
                    logger.warning("ESMFold rate-limited, retrying in %ds …", wait)
                    time.sleep(wait)
                    continue
                logger.warning("ESMFold HTTP error: %s — falling back to AlphaFold", exc)
                break
            except (requests.ConnectionError, requests.Timeout) as exc:
                logger.warning("ESMFold connection error: %s — falling back to AlphaFold", exc)
                break

        logger.info("Falling back to AlphaFold DB for %s", input_data.protein_id)
        return self._run_alphafold(input_data, accession=accession)

    def _run_esmfold(self, input_data: StructureInput) -> StructureOutput:
        """Submit sequence to ESMFold API and parse pLDDT from B-factor column."""
        seq = input_data.sequence.strip().upper()

        resp = requests.post(
            ESMFOLD_API,
            data=seq,
            headers={"Content-Type": "text/plain"},
            timeout=120,
        )
        resp.raise_for_status()
        pdb_text = resp.text

        pdb_path = REPORTS_DIR / f"{input_data.protein_id}_esmfold.pdb"
        pdb_path.write_text(pdb_text)

        # Parse pLDDT from B-factor column of ATOM records
        plddt_scores = []
        for line in pdb_text.splitlines():
            if line.startswith("ATOM"):
                try:
                    bfactor = float(line[60:66].strip())
                    plddt_scores.append(bfactor)
                except (ValueError, IndexError):
                    continue

        mean_plddt = sum(plddt_scores) / len(plddt_scores) if plddt_scores else 0.0
        confidence = round(mean_plddt / 100.0, 4)  # Normalize to 0-1

        logger.info(
            "ESMFold prediction complete for %s — mean pLDDT %.1f",
            input_data.protein_id, mean_plddt,
        )

        return StructureOutput(
            protein_id=input_data.protein_id,
            pdb_path=str(pdb_path),
            confidence_score=confidence,
            method_used="esmfold",
            novel=confidence > 0.7,
            critique_required=True,
        )

    def _run_alphafold(
        self, input_data: StructureInput, *, accession: str | None = None,
    ) -> StructureOutput:
        """Look up pre-computed AlphaFold structure by UniProt accession."""
        # Resolve gene name → UniProt accession if needed
        if not accession:
            _, accession = self._fetch_uniprot_sequence(input_data.protein_id)
        if not accession:
            logger.warning("Could not resolve UniProt accession for %s", input_data.protein_id)
            return self._run_esmfold(input_data)

        # Try AlphaFold DB API
        resp = requests.get(
            f"{ALPHAFOLD_API}/prediction/{accession}",
            timeout=30,
        )
        if resp.status_code == 404:
            logger.warning("No AlphaFold structure for %s (%s)", input_data.protein_id, accession)
            return self._run_esmfold(input_data)
        resp.raise_for_status()

        entries = resp.json()
        if not entries:
            return self._run_esmfold(input_data)

        entry = entries[0] if isinstance(entries, list) else entries
        pdb_url = entry.get("pdbUrl")
        plddt = entry.get("globalMetricValue", 0.0)

        if not pdb_url:
            return self._run_esmfold(input_data)

        pdb_resp = requests.get(pdb_url, timeout=60)
        pdb_resp.raise_for_status()

        pdb_path = REPORTS_DIR / f"{accession}_alphafold.pdb"
        pdb_path.write_text(pdb_resp.text)

        confidence = round(plddt / 100.0, 4) if plddt > 1.0 else round(plddt, 4)

        logger.info(
            "AlphaFold structure retrieved for %s — pLDDT %.1f",
            accession, plddt,
        )

        return StructureOutput(
            protein_id=input_data.protein_id,
            pdb_path=str(pdb_path),
            confidence_score=confidence,
            method_used="alphafold",
            novel=False,
            critique_required=True,
        )
