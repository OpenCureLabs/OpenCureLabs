"""Data flow integration tests — orchestrator → R2 publisher → sweep pipeline.

Verifies the end-to-end data flow guarantees:
- Novel + safe results reach R2 publisher
- Safety-blocked results never reach R2
- Non-novel results skip Grok literature review
- Synthetic results bypass all publishing
- R2 publisher payload structure is correct
- Sweep thresholds (publish ≥ 7.0, reject < 5.0) are enforced
"""

import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "packages", "agentiq_labclaw"))

PROJECT_ROOT = os.path.join(os.path.dirname(__file__), "..")
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


class MockSkillOutput(BaseModel):
    """Mock skill output matching the BaseModel interface expected by post_execute."""

    result_data: dict = {}
    confidence_score: float = 0.95
    novel: bool = False
    critique_required: bool = False
    synthetic: bool = False


# ── Orchestrator → R2 Data Flow ──────────────────────────────────────────────


class TestOrchestratorR2Flow:
    """Verify that post_execute calls R2 publisher only when appropriate."""

    @pytest.mark.asyncio
    async def test_novel_safe_result_reaches_r2(self):
        """Novel + safe → R2.publish_result is called."""
        from agentiq_labclaw.orchestrator import _get_config, post_execute

        if hasattr(_get_config, "_cache"):
            del _get_config._cache

        output = MockSkillOutput(
            result_data={"binding_affinity_kcal": -9.5, "novel": True},
            novel=True,
            critique_required=True,
            confidence_score=0.95,
        )

        mock_critique = {"overall_score": 9, "recommendation": "publish"}
        mock_r2_result = {"id": "r2-123", "url": "https://pub.example.com/r2-123.json"}

        # Clear PYTEST_CURRENT_TEST to allow R2 path to execute
        env_patch = {k: v for k, v in os.environ.items() if k != "PYTEST_CURRENT_TEST"}

        with patch("reviewer.grok_reviewer.GrokReviewer.critique", return_value=mock_critique), \
             patch("reviewer.grok_reviewer.GrokReviewer.review_literature", return_value={"literature_score": 8}), \
             patch("agentiq_labclaw.db.critique_log.log_critique", return_value=1), \
             patch("agentiq_labclaw.db.experiment_results.store_result", return_value=1), \
             patch("agentiq_labclaw.guardrails.novelty_filter.db_check_novelty", return_value=True), \
             patch("agentiq_labclaw.guardrails.safety_check.safety_check", return_value=(True, None)), \
             patch("agentiq_labclaw.publishers.pdf_publisher.PDFPublisher.generate_report", return_value="/tmp/r.pdf"), \
             patch("agentiq_labclaw.publishers.r2_publisher.R2Publisher.enabled", new_callable=lambda: property(lambda self: True)), \
             patch("agentiq_labclaw.publishers.r2_publisher.R2Publisher.publish_result", return_value=mock_r2_result) as mock_pub, \
             patch.dict(os.environ, env_patch, clear=True):

            result = await post_execute("docking", output, run_id=1)

        mock_pub.assert_called_once()
        call_kwargs = mock_pub.call_args
        assert call_kwargs[0][0] == "docking"  # skill_name
        assert call_kwargs[1].get("novel") is True or call_kwargs[0][2] is True
        assert any("r2:" in p for p in result["orchestration"]["published"])

    @pytest.mark.asyncio
    async def test_safety_blocked_result_never_reaches_r2(self):
        """Safety check blocks → R2.publish_result must NOT be called."""
        from agentiq_labclaw.orchestrator import _get_config, post_execute

        if hasattr(_get_config, "_cache"):
            del _get_config._cache

        output = MockSkillOutput(
            result_data={"test": 1},
            novel=True,
            critique_required=True,
            confidence_score=0.001,  # Very low
        )

        # Safety blocks (no critique completed + low confidence)
        with patch("reviewer.grok_reviewer.GrokReviewer.critique", side_effect=Exception("API down")), \
             patch("agentiq_labclaw.publishers.r2_publisher.R2Publisher.publish_result") as mock_pub:

            result = await post_execute("test_skill", output, run_id=None)

        mock_pub.assert_not_called()
        assert result["orchestration"]["safety"]["safe"] is False

    @pytest.mark.asyncio
    async def test_synthetic_result_never_reaches_r2(self):
        """Synthetic results must bypass all publishing."""
        from agentiq_labclaw.orchestrator import _get_config, post_execute

        if hasattr(_get_config, "_cache"):
            del _get_config._cache

        output = MockSkillOutput(
            result_data={"test": 1, "synthetic": True},
            novel=True,
            critique_required=True,
            confidence_score=0.95,
            synthetic=True,
        )

        with patch("agentiq_labclaw.publishers.r2_publisher.R2Publisher.publish_result") as mock_pub, \
             patch("agentiq_labclaw.publishers.pdf_publisher.PDFPublisher.generate_report") as mock_pdf:

            result = await post_execute("test_skill", output, run_id=1)

        mock_pub.assert_not_called()
        mock_pdf.assert_not_called()
        assert result["orchestration"]["published"] == []

    @pytest.mark.asyncio
    async def test_non_novel_skips_literature_review(self):
        """Non-novel results must not trigger Grok literature review."""
        from agentiq_labclaw.orchestrator import _get_config, post_execute

        if hasattr(_get_config, "_cache"):
            del _get_config._cache

        output = MockSkillOutput(
            result_data={"test": 1},
            novel=False,
            critique_required=True,
            confidence_score=0.9,
        )

        mock_critique = {"overall_score": 8, "recommendation": "publish"}

        with patch("reviewer.grok_reviewer.GrokReviewer.critique", return_value=mock_critique), \
             patch("reviewer.grok_reviewer.GrokReviewer.review_literature") as mock_lit, \
             patch("agentiq_labclaw.db.critique_log.log_critique", return_value=1), \
             patch("agentiq_labclaw.guardrails.safety_check.safety_check", return_value=(True, None)), \
             patch("agentiq_labclaw.publishers.pdf_publisher.PDFPublisher.generate_report", return_value="/tmp/r.pdf"):

            result = await post_execute("test_skill", output, run_id=1)

        mock_lit.assert_not_called()
        reviewers = [c["reviewer"] for c in result["orchestration"]["critiques"] if "reviewer" in c]
        assert "grok_literature" not in reviewers

    @pytest.mark.asyncio
    async def test_novel_result_triggers_literature_review(self):
        """Novel + critique_required → Grok literature review is called."""
        from agentiq_labclaw.orchestrator import _get_config, post_execute

        if hasattr(_get_config, "_cache"):
            del _get_config._cache

        output = MockSkillOutput(
            result_data={"neoantigen": "AAAL"},
            novel=True,
            critique_required=True,
            confidence_score=0.9,
        )

        mock_critique = {"overall_score": 8, "recommendation": "publish"}
        mock_lit = {"literature_score": 7, "confidence_in_finding": "high"}

        with patch("reviewer.grok_reviewer.GrokReviewer.critique", return_value=mock_critique), \
             patch("reviewer.grok_reviewer.GrokReviewer.review_literature", return_value=mock_lit) as mock_lit_fn, \
             patch("agentiq_labclaw.db.critique_log.log_critique", return_value=1), \
             patch("agentiq_labclaw.db.experiment_results.store_result", return_value=1), \
             patch("agentiq_labclaw.guardrails.novelty_filter.db_check_novelty", return_value=True), \
             patch("agentiq_labclaw.guardrails.safety_check.safety_check", return_value=(True, None)), \
             patch("agentiq_labclaw.publishers.pdf_publisher.PDFPublisher.generate_report", return_value="/tmp/r.pdf"):

            result = await post_execute("neoantigen_prediction", output, run_id=1)

        mock_lit_fn.assert_called_once()
        reviewers = [c["reviewer"] for c in result["orchestration"]["critiques"] if "reviewer" in c]
        assert "grok_literature" in reviewers


# ── R2 Publisher Contract ────────────────────────────────────────────────────


class TestR2PublisherContract:
    """Verify R2Publisher payload structure and error handling."""

    def test_payload_includes_required_fields(self):
        """Published payload must include skill, result_data, novel, contributor_id, species, summary."""
        from agentiq_labclaw.publishers.r2_publisher import R2Publisher

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"id": "r2-1", "url": "https://example.com/r2-1.json"}

        with patch.dict(os.environ, {"OPENCURELABS_INGEST_URL": "https://ingest.example.com"}), \
             patch("agentiq_labclaw.publishers.r2_publisher.get_or_create_keypair", return_value=(b"key", "pubhex")), \
             patch("agentiq_labclaw.publishers.r2_publisher.sign_payload", return_value="sig123"), \
             patch("agentiq_labclaw.publishers.r2_publisher.requests.post", return_value=mock_resp) as mock_post:

            pub = R2Publisher()
            pub._contributor_id = "test-contributor-id"
            result = pub.publish_result(
                skill_name="structure_prediction",
                result_data={"confidence_score": 0.85, "species": "human"},
                novel=True,
                local_critique={"score": 8},
            )

        assert result is not None
        # Verify the POST body
        call_args = mock_post.call_args
        body = call_args[1]["data"] if "data" in call_args[1] else call_args[0][1] if len(call_args[0]) > 1 else None
        if body is None:
            body = call_args.kwargs.get("data")
        payload = json.loads(body)

        assert payload["skill"] == "structure_prediction"
        assert payload["novel"] is True
        assert payload["contributor_id"] == "test-contributor-id"
        assert payload["species"] == "human"
        assert "summary" in payload
        assert payload["local_critique"] == {"score": 8}

    def test_401_triggers_re_registration(self):
        """First 401 → register contributor → retry POST."""
        from agentiq_labclaw.publishers.r2_publisher import R2Publisher

        resp_401 = MagicMock()
        resp_401.status_code = 401

        resp_200 = MagicMock()
        resp_200.status_code = 200
        resp_200.raise_for_status = MagicMock()
        resp_200.json.return_value = {"id": "r2-2", "url": "https://example.com/r2-2.json"}

        with patch.dict(os.environ, {"OPENCURELABS_INGEST_URL": "https://ingest.example.com"}), \
             patch("agentiq_labclaw.publishers.r2_publisher.get_or_create_keypair", return_value=(b"key", "pubhex")), \
             patch("agentiq_labclaw.publishers.r2_publisher.sign_payload", return_value="sig123"), \
             patch("agentiq_labclaw.publishers.r2_publisher.requests.post", side_effect=[resp_401, resp_200, resp_200]) as mock_post:
            # Third resp_200 for _register_contributor POST

            pub = R2Publisher()
            pub._contributor_id = "test-id"
            result = pub.publish_result(
                skill_name="docking", result_data={"affinity": -9.0}, novel=True,
            )

        assert result is not None
        # Should have called POST 3 times: initial, register, retry
        assert mock_post.call_count == 3

    def test_disabled_when_no_ingest_url(self):
        """R2Publisher.enabled is False when OPENCURELABS_INGEST_URL is not set."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OPENCURELABS_INGEST_URL", None)
            from agentiq_labclaw.publishers.r2_publisher import R2Publisher

            pub = R2Publisher()
            assert pub.enabled is False
            assert pub.publish_result("skill", {}) is None

    def test_network_failure_returns_none(self):
        """RequestException → returns None (result not lost, stored locally)."""
        import requests as req

        from agentiq_labclaw.publishers.r2_publisher import R2Publisher

        with patch.dict(os.environ, {"OPENCURELABS_INGEST_URL": "https://ingest.example.com"}), \
             patch("agentiq_labclaw.publishers.r2_publisher.get_or_create_keypair", return_value=(b"key", "pubhex")), \
             patch("agentiq_labclaw.publishers.r2_publisher.sign_payload", return_value="sig"), \
             patch("agentiq_labclaw.publishers.r2_publisher.requests.post", side_effect=req.ConnectionError("timeout")):

            pub = R2Publisher()
            pub._contributor_id = "test-id"
            result = pub.publish_result("skill", {"data": 1}, novel=False)

        assert result is None


# ── R2 Publisher Summary Extraction ──────────────────────────────────────────


class TestR2SummaryExtraction:
    """Verify _extract_summary and _extract_species produce correct index data."""

    def test_extract_summary_picks_known_fields(self):
        from agentiq_labclaw.publishers.r2_publisher import _extract_summary

        result = {"confidence_score": 0.85, "gene": "TP53", "best_affinity": -9.0, "extra": "ignored"}
        summary = _extract_summary(result)
        assert summary == {"confidence_score": 0.85, "gene": "TP53", "best_affinity": -9.0}
        assert "extra" not in summary

    def test_extract_species_defaults_to_human(self):
        from agentiq_labclaw.publishers.r2_publisher import _extract_species

        assert _extract_species({}) == "human"
        assert _extract_species({"species": "dog"}) == "dog"
        assert _extract_species({"species": ""}) == "human"
        assert _extract_species({"species": None}) == "human"


# ── Sweep Threshold Logic ────────────────────────────────────────────────────


class TestSweepThresholds:
    """Verify sweep's publish/reject/defer decision boundaries."""

    def test_threshold_constants(self):
        """Verify the threshold constants haven't drifted from documented values."""
        from reviewer.sweep import PUBLISH_THRESHOLD, REJECT_THRESHOLD

        assert PUBLISH_THRESHOLD == 7.0, "Publish threshold must be 7.0"
        assert REJECT_THRESHOLD == 5.0, "Reject threshold must be 5.0"

    def test_get_pending_filters_novel_only(self):
        """get_pending_results(novel_only=True) must pass novel=true param."""
        mock_response = {"results": []}

        with patch("reviewer.sweep.api_get", return_value=mock_response) as mock_get:
            from reviewer.sweep import get_pending_results

            results = get_pending_results(limit=10, novel_only=True)

        mock_get.assert_called_once()
        call_args = mock_get.call_args
        params = call_args[0][1] if len(call_args[0]) > 1 else call_args[1].get("params", {})
        assert params.get("novel") == "true"
        assert params.get("status") == "pending"

    def test_get_pending_without_novel_filter(self):
        """get_pending_results(novel_only=False) must not include novel param."""
        mock_response = {"results": []}

        with patch("reviewer.sweep.api_get", return_value=mock_response) as mock_get:
            from reviewer.sweep import get_pending_results

            results = get_pending_results(limit=5, novel_only=False)

        call_args = mock_get.call_args
        params = call_args[0][1] if len(call_args[0]) > 1 else call_args[1].get("params", {})
        assert "novel" not in params

    def test_auto_publish_replications_no_grok(self):
        """Replications auto-publish without Grok review call."""
        mock_results = {"results": [
            {"id": "rep-1", "skill": "structure_prediction", "novel": False},
        ]}

        with patch("reviewer.sweep.api_get", return_value=mock_results), \
             patch("reviewer.sweep.api_patch") as mock_patch:

            from reviewer.sweep import auto_publish_replications

            count = auto_publish_replications(limit=10)

        assert count == 1
        mock_patch.assert_called_once()
        patch_data = mock_patch.call_args[0][1]
        assert patch_data["status"] == "published"
        assert patch_data["batch_critique"]["auto_published"] is True


# ── Orchestrator Novel Propagation ───────────────────────────────────────────


class TestNovelPropagation:
    """Verify that the novel flag from skill output flows correctly through the pipeline."""

    @pytest.mark.asyncio
    async def test_novel_flag_read_from_result_dict(self):
        """post_execute reads novel from result.model_dump()['novel']."""
        from agentiq_labclaw.orchestrator import _get_config, post_execute

        if hasattr(_get_config, "_cache"):
            del _get_config._cache

        output = MockSkillOutput(
            result_data={"test": 1},
            novel=True,
            critique_required=False,
            confidence_score=0.9,
        )

        with patch("agentiq_labclaw.guardrails.novelty_filter.db_check_novelty", return_value=True), \
             patch("agentiq_labclaw.guardrails.safety_check.safety_check", return_value=(True, None)), \
             patch("agentiq_labclaw.publishers.pdf_publisher.PDFPublisher.generate_report", return_value="/tmp/r.pdf"):

            result = await post_execute("test_skill", output, run_id=1)

        # The result dict should preserve the novel flag
        assert result["result"]["novel"] is True

    @pytest.mark.asyncio
    async def test_novel_false_not_overridden(self):
        """novel=False in skill output must not become True anywhere in the pipeline."""
        from agentiq_labclaw.orchestrator import _get_config, post_execute

        if hasattr(_get_config, "_cache"):
            del _get_config._cache

        output = MockSkillOutput(
            result_data={"test": 1},
            novel=False,
            critique_required=False,
            confidence_score=0.9,
        )

        with patch("agentiq_labclaw.guardrails.safety_check.safety_check", return_value=(True, None)), \
             patch("agentiq_labclaw.publishers.pdf_publisher.PDFPublisher.generate_report", return_value="/tmp/r.pdf"):

            result = await post_execute("test_skill", output, run_id=1)

        assert result["result"]["novel"] is False
        # Novelty filter should not have run (novel was False)
        assert result["orchestration"]["novelty"] is None
