"""ChEMBL compound bioactivity connector."""

import logging

logger = logging.getLogger("labclaw.connectors.chembl")


class ChEMBLConnector:
    """Connector for ChEMBL drug bioactivity data."""

    BASE_URL = "https://www.ebi.ac.uk/chembl/api/data"

    def search_compound(self, smiles: str) -> list[dict]:
        """Search ChEMBL for compounds by SMILES similarity."""
        logger.info("Searching ChEMBL for compound: %s", smiles[:50])
        # TODO: Implement ChEMBL REST API similarity search
        return []

    def get_bioactivities(self, chembl_id: str, target: str | None = None) -> list[dict]:
        """Get bioactivity data for a compound."""
        logger.info("Fetching bioactivities for %s", chembl_id)
        # TODO: Implement ChEMBL bioactivity query
        return []

    def get_target_info(self, target_chembl_id: str) -> dict | None:
        """Get target protein information from ChEMBL."""
        logger.info("Fetching target info: %s", target_chembl_id)
        # TODO: Implement ChEMBL target query
        return None
