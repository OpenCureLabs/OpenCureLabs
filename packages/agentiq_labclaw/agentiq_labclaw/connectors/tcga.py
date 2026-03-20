"""TCGA / GEO data ingestion connector."""

import json
import logging
from pathlib import Path

from agentiq_labclaw.connectors._http import resilient_session

logger = logging.getLogger("labclaw.connectors.tcga")


class TCGAConnector:
    """Connector for TCGA (via GDC API) and GEO cancer genomics data."""

    GDC_BASE = "https://api.gdc.cancer.gov"
    GEO_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

    def __init__(self, timeout: int = 30):
        self.timeout = timeout
        self._session = resilient_session(timeout=timeout)

    def query_cases(
        self,
        project_id: str,
        data_type: str = "Gene Expression Quantification",
        size: int = 100,
    ) -> list[dict]:
        """Query TCGA cases by project and data type via the GDC API."""
        logger.info("Querying TCGA cases for project %s (type: %s)", project_id, data_type)

        filters = {
            "op": "and",
            "content": [
                {"op": "=", "content": {"field": "cases.project.project_id", "value": project_id}},
                {"op": "=", "content": {"field": "data_type", "value": data_type}},
            ],
        }
        params = {
            "filters": json.dumps(filters),
            "fields": "file_id,file_name,cases.case_id,cases.submitter_id,data_type,file_size",
            "size": str(size),
            "format": "JSON",
        }

        resp = self._session.get(
            f"{self.GDC_BASE}/files",
            params=params,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        data = resp.json()

        hits = data.get("data", {}).get("hits", [])
        logger.info("Found %d files for project %s", len(hits), project_id)
        return hits

    def download_files(self, file_ids: list[str], output_dir: str) -> list[str]:
        """Download TCGA data files by GDC file UUID."""
        logger.info("Downloading %d TCGA files to %s", len(file_ids), output_dir)
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)

        downloaded = []
        for fid in file_ids:
            resp = self._session.get(
                f"{self.GDC_BASE}/data/{fid}",
                timeout=120,
                stream=True,
            )
            resp.raise_for_status()

            # GDC returns Content-Disposition with filename
            cd = resp.headers.get("Content-Disposition", "")
            if "filename=" in cd:
                fname = cd.split("filename=")[-1].strip('" ')
            else:
                fname = fid
            dest = out / fname
            with open(dest, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)

            downloaded.append(str(dest))
            logger.info("Downloaded %s → %s", fid, dest)

        return downloaded

    def query_geo(self, accession: str) -> dict:
        """Query GEO for dataset metadata by accession (e.g. GSE12345)."""
        logger.info("Querying GEO accession: %s", accession)

        # Use NCBI E-utilities esearch → esummary
        search_resp = self._session.get(
            f"{self.GEO_BASE}/esearch.fcgi",
            params={"db": "gds", "term": accession, "retmode": "json"},
            timeout=self.timeout,
        )
        search_resp.raise_for_status()
        search_data = search_resp.json()

        id_list = search_data.get("esearchresult", {}).get("idlist", [])
        if not id_list:
            logger.warning("No GEO results for %s", accession)
            return {}

        summary_resp = self._session.get(
            f"{self.GEO_BASE}/esummary.fcgi",
            params={"db": "gds", "id": ",".join(id_list), "retmode": "json"},
            timeout=self.timeout,
        )
        summary_resp.raise_for_status()
        summary = summary_resp.json().get("result", {})

        # Return the first result's metadata
        for uid in id_list:
            if uid in summary:
                return summary[uid]
        return summary
