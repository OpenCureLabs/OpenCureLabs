"""ClinVar / OMIM variant lookup connector."""

import logging

from agentiq_labclaw.connectors._http import resilient_session

logger = logging.getLogger("labclaw.connectors.clinvar")


class ClinVarConnector:
    """Connector for ClinVar (via NCBI E-utilities) and OMIM variant databases."""

    EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
    CLINVAR_API = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

    def __init__(self, timeout: int = 30):
        self.timeout = timeout
        self._session = resilient_session(timeout=timeout)

    def lookup_variant(self, variant_id: str) -> dict | None:
        """Look up a variant in ClinVar by ID (e.g. '12345') or HGVS notation."""
        logger.info("Looking up variant in ClinVar: %s", variant_id)

        # esearch to find the ClinVar UID
        search_resp = self._session.get(
            f"{self.EUTILS_BASE}/esearch.fcgi",
            params={"db": "clinvar", "term": variant_id, "retmode": "json"},
            timeout=self.timeout,
        )
        search_resp.raise_for_status()
        id_list = search_resp.json().get("esearchresult", {}).get("idlist", [])

        if not id_list:
            logger.warning("No ClinVar results for %s", variant_id)
            return None

        # esummary for the first match
        summary_resp = self._session.get(
            f"{self.EUTILS_BASE}/esummary.fcgi",
            params={"db": "clinvar", "id": id_list[0], "retmode": "json"},
            timeout=self.timeout,
        )
        summary_resp.raise_for_status()
        result = summary_resp.json().get("result", {})

        entry = result.get(id_list[0], {})
        if not entry:
            return None

        return {
            "uid": id_list[0],
            "title": entry.get("title"),
            "clinical_significance": (
                entry.get("clinical_significance", {}).get("description")
                if isinstance(entry.get("clinical_significance"), dict)
                else entry.get("clinical_significance")
            ),
            "gene_sort": entry.get("gene_sort"),
            "variation_set": entry.get("variation_set"),
            "trait_set": entry.get("trait_set"),
        }

    def search_gene(self, gene_symbol: str, limit: int = 50) -> list[dict]:
        """Search ClinVar for pathogenic/likely pathogenic variants in a gene."""
        logger.info("Searching ClinVar for gene: %s", gene_symbol)

        term = f"{gene_symbol}[gene] AND (pathogenic[clinsig] OR likely_pathogenic[clinsig])"
        search_resp = self._session.get(
            f"{self.EUTILS_BASE}/esearch.fcgi",
            params={"db": "clinvar", "term": term, "retmax": limit, "retmode": "json"},
            timeout=self.timeout,
        )
        search_resp.raise_for_status()
        id_list = search_resp.json().get("esearchresult", {}).get("idlist", [])

        if not id_list:
            return []

        # Batch fetch summaries
        summary_resp = self._session.get(
            f"{self.EUTILS_BASE}/esummary.fcgi",
            params={"db": "clinvar", "id": ",".join(id_list), "retmode": "json"},
            timeout=self.timeout,
        )
        summary_resp.raise_for_status()
        result = summary_resp.json().get("result", {})

        variants = []
        for uid in id_list:
            entry = result.get(uid, {})
            if not entry or uid == "uids":
                continue
            variants.append({
                "uid": uid,
                "title": entry.get("title"),
                "clinical_significance": (
                    entry.get("clinical_significance", {}).get("description")
                    if isinstance(entry.get("clinical_significance"), dict)
                    else entry.get("clinical_significance")
                ),
                "gene_sort": entry.get("gene_sort"),
            })

        logger.info("Found %d pathogenic variants for %s", len(variants), gene_symbol)
        return variants

    def lookup_omim(self, gene_symbol: str) -> list[dict]:
        """Look up gene-disease associations via NCBI MedGen (OMIM-linked)."""
        logger.info("Looking up OMIM/MedGen associations for: %s", gene_symbol)

        # Use MedGen database to find OMIM-linked gene-disease associations
        search_resp = self._session.get(
            f"{self.EUTILS_BASE}/esearch.fcgi",
            params={"db": "medgen", "term": f"{gene_symbol}[gene]", "retmax": 20, "retmode": "json"},
            timeout=self.timeout,
        )
        search_resp.raise_for_status()
        id_list = search_resp.json().get("esearchresult", {}).get("idlist", [])

        if not id_list:
            return []

        summary_resp = self._session.get(
            f"{self.EUTILS_BASE}/esummary.fcgi",
            params={"db": "medgen", "id": ",".join(id_list), "retmode": "json"},
            timeout=self.timeout,
        )
        summary_resp.raise_for_status()
        result = summary_resp.json().get("result", {})

        associations = []
        for uid in id_list:
            entry = result.get(uid, {})
            if not entry or uid == "uids":
                continue
            associations.append({
                "uid": uid,
                "concept_name": entry.get("title") or entry.get("conceptname"),
                "definition": entry.get("definition"),
                "semantic_type": entry.get("semantictype"),
            })

        logger.info("Found %d MedGen associations for %s", len(associations), gene_symbol)
        return associations
