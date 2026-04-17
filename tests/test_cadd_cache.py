"""Tests for the on-disk CADD cache in variant_pathogenicity."""

import json
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def cache_dir(tmp_path, monkeypatch):
    d = tmp_path / "cadd"
    monkeypatch.setenv("CADD_CACHE_DIR", str(d))
    monkeypatch.delenv("CADD_CACHE_DISABLE", raising=False)
    # Reload the module so the new CADD_CACHE_DIR is picked up at import time
    import importlib

    import agentiq_labclaw.skills.variant_pathogenicity as vp

    importlib.reload(vp)
    return d, vp


class TestCaddCache:
    def test_first_call_hits_api_and_writes_cache(self, cache_dir):
        d, vp = cache_dir
        mock_resp = MagicMock(status_code=200)
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = [{"PHRED": 27.4}]

        with patch("agentiq_labclaw.skills.variant_pathogenicity.requests.get",
                   return_value=mock_resp) as mock_get:
            score = vp._query_cadd("chr1", 12345, "A", "T")

        assert score == pytest.approx(27.4)
        assert mock_get.call_count == 1
        cached = json.loads((d / "chr1_12345_A_T.json").read_text())
        assert cached["score"] == pytest.approx(27.4)

    def test_second_call_uses_cache(self, cache_dir):
        d, vp = cache_dir
        (d).mkdir(parents=True, exist_ok=True)
        (d / "chr1_12345_A_T.json").write_text(json.dumps({"score": 31.2}))

        with patch("agentiq_labclaw.skills.variant_pathogenicity.requests.get") as mock_get:
            score = vp._query_cadd("chr1", 12345, "A", "T")

        assert score == pytest.approx(31.2)
        mock_get.assert_not_called()

    def test_negative_cache_avoids_refetch_on_404(self, cache_dir):
        d, vp = cache_dir
        # First call returns 404, should cache null
        mock_resp = MagicMock(status_code=404)
        with patch("agentiq_labclaw.skills.variant_pathogenicity.requests.get",
                   return_value=mock_resp) as mock_get:
            score = vp._query_cadd("chrX", 99999, "G", "C")
            assert score is None
            assert mock_get.call_count == 1

        # Second call should NOT hit the API
        with patch("agentiq_labclaw.skills.variant_pathogenicity.requests.get") as mock_get2:
            score = vp._query_cadd("chrX", 99999, "G", "C")
            assert score is None
            mock_get2.assert_not_called()

    def test_cache_disable_env_bypasses_cache(self, cache_dir, monkeypatch):
        d, vp = cache_dir
        (d).mkdir(parents=True, exist_ok=True)
        (d / "chr2_222_C_G.json").write_text(json.dumps({"score": 15.0}))
        monkeypatch.setenv("CADD_CACHE_DISABLE", "1")

        mock_resp = MagicMock(status_code=200)
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = [{"PHRED": 22.0}]
        with patch("agentiq_labclaw.skills.variant_pathogenicity.requests.get",
                   return_value=mock_resp) as mock_get:
            score = vp._query_cadd("chr2", 222, "C", "G")

        # Disabled cache -> must go to the API and must return the fresh value
        assert score == pytest.approx(22.0)
        assert mock_get.call_count == 1

    def test_corrupt_cache_falls_back_to_api(self, cache_dir):
        d, vp = cache_dir
        (d).mkdir(parents=True, exist_ok=True)
        (d / "chr3_333_T_A.json").write_text("this is not json {{{")

        mock_resp = MagicMock(status_code=200)
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = [{"PHRED": 18.0}]
        with patch("agentiq_labclaw.skills.variant_pathogenicity.requests.get",
                   return_value=mock_resp) as mock_get:
            score = vp._query_cadd("chr3", 333, "T", "A")

        assert score == pytest.approx(18.0)
        assert mock_get.call_count == 1
