"""TCGA / GEO data ingestion connector."""

import logging

logger = logging.getLogger("labclaw.connectors.tcga")


class TCGAConnector:
    """Connector for TCGA and GEO cancer genomics data."""

    BASE_URL = "https://api.gdc.cancer.gov"

    def query_cases(self, project_id: str, data_type: str = "Gene Expression Quantification") -> list[dict]:
        """Query TCGA cases by project and data type."""
        logger.info("Querying TCGA cases for project %s", project_id)
        # TODO: Implement GDC API query
        return []

    def download_files(self, file_ids: list[str], output_dir: str) -> list[str]:
        """Download TCGA data files by ID."""
        logger.info("Downloading %d TCGA files to %s", len(file_ids), output_dir)
        # TODO: Implement GDC download
        return []

    def query_geo(self, accession: str) -> dict:
        """Query GEO for dataset metadata by accession number."""
        logger.info("Querying GEO accession: %s", accession)
        # TODO: Implement GEO query via Entrez
        return {}
