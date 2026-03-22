"""
OMIA (Online Mendelian Inheritance in Animals) connector.

OMIA is the veterinary equivalent of ClinVar/OMIM — a curated database of
known genetic diseases and traits in animals.

API docs: https://omia.org/api/ (public, no auth required)

Usage:
    from agentiq_labclaw.connectors.omia import OMIAConnector
    conn = OMIAConnector()
    results = conn.lookup_gene("BRAF", species="canis_lupus_familiaris")
"""

from __future__ import annotations

import logging

import requests

logger = logging.getLogger("labclaw.connectors.omia")

OMIA_API = "https://omia.org/api"
DEFAULT_TIMEOUT = 20


class OMIAConnector:
    """Client for the OMIA REST API."""

    def __init__(self, timeout: int = DEFAULT_TIMEOUT) -> None:
        self._timeout = timeout
        self._session = requests.Session()
        self._session.headers.update({"Accept": "application/json"})

    def lookup_gene(
        self,
        gene: str,
        species: str = "canis_lupus_familiaris",
    ) -> list[dict]:
        """
        Look up known OMIA disease associations for a gene in a given species.

        Args:
            gene: Gene symbol (e.g. "BRAF", "KIT", "TP53").
            species: Latin binomial string as accepted by OMIA
                     (e.g. "canis_lupus_familiaris", "felis_catus").

        Returns:
            List of association dicts with keys: omia_id, phene, inheritance,
            gene_symbol, species, molecular_basis, pubmed_ids.
            Empty list if no associations are found or the API is unreachable.
        """
        try:
            # OMIA search endpoint
            url = f"{OMIA_API}/phene/"
            resp = self._session.get(
                url,
                params={"gene_symbol": gene, "species_name": species},
                timeout=self._timeout,
            )
            if resp.status_code == 404:
                return []
            resp.raise_for_status()
            data = resp.json()

            associations = []
            for entry in data.get("results", []):
                assoc = {
                    "omia_id": entry.get("omia_id", ""),
                    "phene": entry.get("phene_name", ""),
                    "inheritance": entry.get("inherit", ""),
                    "gene_symbol": entry.get("gene_symbol", gene),
                    "species": species,
                    "molecular_basis": entry.get("molecular_basis", ""),
                    "pubmed_ids": entry.get("pubmed_ids", []),
                    "source": "OMIA",
                }
                associations.append(assoc)

            logger.info(
                "OMIA: %d associations for %s in %s",
                len(associations), gene, species,
            )
            return associations

        except requests.exceptions.ConnectionError:
            logger.warning("OMIA API unreachable — skipping gene lookup for %s", gene)
            return []
        except Exception as exc:
            logger.warning("OMIA lookup failed for %s (%s): %s", gene, species, exc)
            return []

    def lookup_phene(self, omia_id: str) -> dict | None:
        """
        Fetch full details for a specific OMIA phene by its OMIA ID.

        Args:
            omia_id: OMIA phenotype ID (e.g. "001356").

        Returns:
            Dict of phene details, or None if not found.
        """
        try:
            resp = self._session.get(
                f"{OMIA_API}/phene/{omia_id}/",
                timeout=self._timeout,
            )
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            logger.warning("OMIA phene lookup failed for %s: %s", omia_id, exc)
            return None
