"""Tests for data connectors: TCGA/GEO, ChEMBL, ClinVar."""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "packages", "agentiq_labclaw"))

from agentiq_labclaw.connectors.tcga import TCGAConnector
from agentiq_labclaw.connectors.chembl import ChEMBLConnector
from agentiq_labclaw.connectors.clinvar import ClinVarConnector


# ── TCGA Connector ───────────────────────────────────────────────────────────


class TestTCGAConnector:
    def setup_method(self):
        self.conn = TCGAConnector(timeout=5)

    @patch("agentiq_labclaw.connectors.tcga.requests.get")
    def test_query_cases(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "data": {
                    "hits": [
                        {"file_id": "abc-123", "file_name": "exp.tsv", "data_type": "Gene Expression Quantification"},
                        {"file_id": "def-456", "file_name": "exp2.tsv", "data_type": "Gene Expression Quantification"},
                    ]
                }
            },
        )
        mock_get.return_value.raise_for_status = MagicMock()
        results = self.conn.query_cases("TCGA-BRCA", size=2)
        assert len(results) == 2
        assert results[0]["file_id"] == "abc-123"
        mock_get.assert_called_once()

    @patch("agentiq_labclaw.connectors.tcga.requests.get")
    def test_query_geo(self, mock_get):
        # Two calls: esearch then esummary
        search_resp = MagicMock(
            status_code=200,
            json=lambda: {"esearchresult": {"idlist": ["200012345"]}},
        )
        summary_resp = MagicMock(
            status_code=200,
            json=lambda: {
                "result": {
                    "200012345": {
                        "uid": "200012345",
                        "title": "Test GSE",
                        "summary": "A study",
                        "gpl": "GPL570",
                        "n_samples": 100,
                    }
                }
            },
        )
        mock_get.side_effect = [search_resp, summary_resp]
        result = self.conn.query_geo("GSE12345")
        assert result["title"] == "Test GSE"

    @patch("agentiq_labclaw.connectors.tcga.requests.get")
    def test_download_files(self, mock_get, tmp_path):
        mock_get.return_value = MagicMock(
            status_code=200,
            iter_content=lambda chunk_size: [b"file data"],
            headers={"Content-Disposition": 'attachment; filename="test.tsv"'},
        )
        paths = self.conn.download_files(["abc-123"], str(tmp_path))
        assert len(paths) == 1


# ── ChEMBL Connector ────────────────────────────────────────────────────────


class TestChEMBLConnector:
    def setup_method(self):
        self.conn = ChEMBLConnector(timeout=5)

    @patch("agentiq_labclaw.connectors.chembl.requests.get")
    def test_search_compound(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "molecules": [
                    {
                        "molecule_chembl_id": "CHEMBL25",
                        "pref_name": "ASPIRIN",
                        "similarity": 100,
                        "molecule_structures": {"canonical_smiles": "CC(=O)Oc1ccccc1C(O)=O"},
                        "max_phase": 4,
                    }
                ]
            },
        )
        results = self.conn.search_compound("CC(=O)Oc1ccccc1C(O)=O", similarity=90)
        assert len(results) >= 1
        assert results[0]["chembl_id"] == "CHEMBL25"

    @patch("agentiq_labclaw.connectors.chembl.requests.get")
    def test_get_bioactivities(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "activities": [
                    {
                        "activity_id": 1,
                        "assay_chembl_id": "CHEMBL_ASSAY_1",
                        "target_chembl_id": "CHEMBL_TARGET_1",
                        "target_pref_name": "Cyclooxygenase-2",
                        "standard_type": "IC50",
                        "standard_value": "10.0",
                        "standard_units": "nM",
                        "standard_relation": "=",
                    }
                ]
            },
        )
        results = self.conn.get_bioactivities("CHEMBL25")
        assert len(results) == 1
        assert results[0]["type"] == "IC50"

    @patch("agentiq_labclaw.connectors.chembl.requests.get")
    def test_get_target_info(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "target_chembl_id": "CHEMBL220",
                "pref_name": "Cyclooxygenase-2",
                "organism": "Homo sapiens",
                "target_type": "SINGLE PROTEIN",
                "target_components": [{"accession": "P35354"}],
            },
        )
        result = self.conn.get_target_info("CHEMBL220")
        assert result is not None
        assert result["pref_name"] == "Cyclooxygenase-2"


# ── ClinVar Connector ───────────────────────────────────────────────────────


class TestClinVarConnector:
    def setup_method(self):
        self.conn = ClinVarConnector(timeout=5)

    @patch("agentiq_labclaw.connectors.clinvar.requests.get")
    def test_lookup_variant(self, mock_get):
        search_resp = MagicMock(
            status_code=200,
            json=lambda: {"esearchresult": {"idlist": ["12345"]}},
        )
        summary_resp = MagicMock(
            status_code=200,
            json=lambda: {
                "result": {
                    "12345": {
                        "uid": "12345",
                        "title": "NM_000546.6(TP53):c.743G>A (p.Arg248Gln)",
                        "clinical_significance": {"description": "Pathogenic"},
                        "gene_sort": "TP53",
                        "variation_set": [],
                        "trait_set": [],
                    }
                }
            },
        )
        mock_get.side_effect = [search_resp, summary_resp]
        result = self.conn.lookup_variant("TP53 c.743G>A")
        assert result is not None
        assert "TP53" in result["title"]

    @patch("agentiq_labclaw.connectors.clinvar.requests.get")
    def test_search_gene(self, mock_get):
        search_resp = MagicMock(
            status_code=200,
            json=lambda: {"esearchresult": {"idlist": ["111", "222"]}},
        )
        summary_resp = MagicMock(
            status_code=200,
            json=lambda: {
                "result": {
                    "111": {"uid": "111", "title": "Variant 1", "clinical_significance": {"description": "Pathogenic"}, "gene_sort": "BRCA1"},
                    "222": {"uid": "222", "title": "Variant 2", "clinical_significance": {"description": "Likely pathogenic"}, "gene_sort": "BRCA1"},
                }
            },
        )
        mock_get.side_effect = [search_resp, summary_resp]
        results = self.conn.search_gene("BRCA1")
        assert len(results) == 2

    @patch("agentiq_labclaw.connectors.clinvar.requests.get")
    def test_lookup_omim(self, mock_get):
        search_resp = MagicMock(
            status_code=200,
            json=lambda: {"esearchresult": {"idlist": ["C0006142"]}},
        )
        summary_resp = MagicMock(
            status_code=200,
            json=lambda: {
                "result": {
                    "C0006142": {
                        "uid": "C0006142",
                        "conceptname": "Breast Cancer",
                        "definition": "Malignant neoplasm of breast",
                        "semantictype": "Disease or Syndrome",
                    }
                }
            },
        )
        mock_get.side_effect = [search_resp, summary_resp]
        results = self.conn.lookup_omim("BRCA1")
        assert len(results) >= 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
