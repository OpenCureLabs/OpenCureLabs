"""ChEMBL compound bioactivity connector."""

import logging

from agentiq_labclaw.connectors._http import resilient_session

logger = logging.getLogger("labclaw.connectors.chembl")


class ChEMBLConnector:
    """Connector for ChEMBL drug bioactivity data via the REST API."""

    BASE_URL = "https://www.ebi.ac.uk/chembl/api/data"

    def __init__(self, timeout: int = 30):
        self.timeout = timeout
        self._headers = {"Accept": "application/json"}
        self._session = resilient_session(timeout=timeout)

    def search_compound(self, smiles: str, similarity: int = 70) -> list[dict]:
        """Search ChEMBL for compounds by SMILES similarity."""
        logger.info("Searching ChEMBL for compound: %s (similarity>=%d%%)", smiles[:50], similarity)

        resp = self._session.get(
            f"{self.BASE_URL}/similarity/{smiles}/{similarity}.json",
            headers=self._headers,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        data = resp.json()

        molecules = data.get("molecules", [])
        results = []
        for mol in molecules:
            results.append({
                "chembl_id": mol.get("molecule_chembl_id"),
                "pref_name": mol.get("pref_name"),
                "similarity": mol.get("similarity"),
                "smiles": (mol.get("molecule_structures") or {}).get("canonical_smiles"),
                "max_phase": mol.get("max_phase"),
            })

        logger.info("Found %d similar compounds", len(results))
        return results

    def get_bioactivities(
        self, chembl_id: str, target: str | None = None, limit: int = 100,
    ) -> list[dict]:
        """Get bioactivity data for a compound, optionally filtered by target."""
        logger.info("Fetching bioactivities for %s", chembl_id)

        params: dict = {
            "molecule_chembl_id": chembl_id,
            "limit": limit,
            "format": "json",
        }
        if target:
            params["target_chembl_id"] = target

        resp = self._session.get(
            f"{self.BASE_URL}/activity.json",
            params=params,
            headers=self._headers,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        data = resp.json()

        activities = data.get("activities", [])
        results = []
        for act in activities:
            results.append({
                "activity_id": act.get("activity_id"),
                "assay_chembl_id": act.get("assay_chembl_id"),
                "target_chembl_id": act.get("target_chembl_id"),
                "target_pref_name": act.get("target_pref_name"),
                "type": act.get("type") or act.get("standard_type"),
                "value": act.get("value") or act.get("standard_value"),
                "units": act.get("units") or act.get("standard_units"),
                "relation": act.get("standard_relation"),
            })

        logger.info("Found %d bioactivities for %s", len(results), chembl_id)
        return results

    def get_target_info(self, target_chembl_id: str) -> dict | None:
        """Get target protein information from ChEMBL."""
        logger.info("Fetching target info: %s", target_chembl_id)

        resp = self._session.get(
            f"{self.BASE_URL}/target/{target_chembl_id}.json",
            headers=self._headers,
            timeout=self.timeout,
        )
        if resp.status_code == 404:
            logger.warning("Target %s not found in ChEMBL", target_chembl_id)
            return None
        resp.raise_for_status()
        data = resp.json()

        return {
            "target_chembl_id": data.get("target_chembl_id"),
            "pref_name": data.get("pref_name"),
            "organism": data.get("organism"),
            "target_type": data.get("target_type"),
            "components": [
                {
                    "component_id": c.get("component_id"),
                    "accession": c.get("accession"),
                    "description": c.get("component_description"),
                }
                for c in data.get("target_components", [])
            ],
        }
