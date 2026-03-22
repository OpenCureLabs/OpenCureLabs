"""Tests for the post-execution orchestrator pipeline."""

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
    """Mock skill output for testing."""

    result_data: dict = {}
    confidence_score: float = 0.95
    novel: bool = False
    critique_required: bool = False


class TestOrchestratorConfig:
    """Test YAML config loading for orchestrator settings."""

    def test_load_config(self):
        from agentiq_labclaw.orchestrator import _load_yaml_config

        config = _load_yaml_config()
        assert isinstance(config, dict)
        # guardrails/publishers are now defaults in orchestrator.py, not in YAML
        assert "llms" in config or "workflow" in config

    def test_guardrails_enabled(self):
        from agentiq_labclaw.orchestrator import _guardrails_enabled

        # Reset cache to force reload
        if hasattr(_guardrails_enabled.__wrapped__ if hasattr(_guardrails_enabled, '__wrapped__') else _guardrails_enabled, '_cache'):
            pass  # Cache is on _get_config

        from agentiq_labclaw.orchestrator import _get_config
        if hasattr(_get_config, '_cache'):
            del _get_config._cache

        assert _guardrails_enabled("output_validation") is True
        assert _guardrails_enabled("nonexistent") is False

    def test_publisher_enabled(self):
        from agentiq_labclaw.orchestrator import _publisher_enabled, _get_config

        if hasattr(_get_config, '_cache'):
            del _get_config._cache

        assert _publisher_enabled("github") is True
        assert _publisher_enabled("pdf") is True
        assert _publisher_enabled("nonexistent") is False


class TestPostExecuteValidation:
    """Test the output validation step of the orchestrator."""

    @pytest.mark.asyncio
    async def test_passes_valid_output(self):
        from agentiq_labclaw.orchestrator import post_execute, _get_config

        if hasattr(_get_config, '_cache'):
            del _get_config._cache

        output = MockSkillOutput(result_data={"test": True}, novel=False, critique_required=False)

        with patch("agentiq_labclaw.guardrails.novelty_filter.db_check_novelty", return_value=True):

            result = await post_execute("test_skill", output)

        assert result["skill_name"] == "test_skill"
        assert result["result"]["result_data"] == {"test": True}


class TestPostExecuteReviewer:
    """Test the reviewer critique step."""

    @pytest.mark.asyncio
    async def test_claude_critique_called_when_required(self):
        from agentiq_labclaw.orchestrator import post_execute, _get_config

        if hasattr(_get_config, '_cache'):
            del _get_config._cache

        output = MockSkillOutput(
            result_data={"binding": -9.0},
            novel=False,
            critique_required=True,
            confidence_score=0.9,
        )

        mock_critique = {
            "overall_score": 8,
            "recommendation": "publish",
            "scientific_logic": {"score": 8, "comments": "good"},
        }

        with patch("reviewer.claude_reviewer.ClaudeReviewer.critique", return_value=mock_critique) as mock_claude, \
             patch("agentiq_labclaw.db.critique_log.log_critique", return_value=1), \
             patch("agentiq_labclaw.guardrails.safety_check.safety_check", return_value=(True, None)), \
             patch("agentiq_labclaw.publishers.pdf_publisher.PDFPublisher.generate_report", return_value="/tmp/test.pdf"), \
             patch("agentiq_labclaw.publishers.github_publisher.GitHubPublisher.commit_result", return_value=True):

            result = await post_execute("test_skill", output, run_id=1)

        orch = result["orchestration"]
        assert len(orch["critiques"]) >= 1
        assert orch["critiques"][0]["reviewer"] == "claude_opus"
        assert orch["critiques"][0]["critique"]["overall_score"] == 8

    @pytest.mark.asyncio
    async def test_grok_called_when_novel(self):
        from agentiq_labclaw.orchestrator import post_execute, _get_config

        if hasattr(_get_config, '_cache'):
            del _get_config._cache

        output = MockSkillOutput(
            result_data={"neoantigen": "MVLSPADKTNV"},
            novel=True,
            critique_required=True,
            confidence_score=0.9,
        )

        mock_critique = {"overall_score": 9, "recommendation": "publish"}
        mock_lit = {"literature_score": 7, "confidence_in_finding": "high", "corroborating": []}

        with patch("reviewer.claude_reviewer.ClaudeReviewer.critique", return_value=mock_critique), \
             patch("reviewer.grok_reviewer.GrokReviewer.review_literature", return_value=mock_lit), \
             patch("agentiq_labclaw.db.critique_log.log_critique", return_value=1), \
             patch("agentiq_labclaw.db.experiment_results.store_result", return_value=1), \
             patch("agentiq_labclaw.guardrails.novelty_filter.db_check_novelty", return_value=True), \
             patch("agentiq_labclaw.guardrails.safety_check.safety_check", return_value=(True, None)), \
             patch("agentiq_labclaw.publishers.pdf_publisher.PDFPublisher.generate_report", return_value="/tmp/test.pdf"), \
             patch("agentiq_labclaw.publishers.github_publisher.GitHubPublisher.commit_result", return_value=True):

            result = await post_execute("neoantigen_prediction", output, run_id=1)

        orch = result["orchestration"]
        critiques = orch["critiques"]
        reviewers = [c["reviewer"] for c in critiques if "reviewer" in c]
        assert "claude_opus" in reviewers
        assert "grok_literature" in reviewers


class TestPostExecuteSafety:
    """Test the safety check gate."""

    @pytest.mark.asyncio
    async def test_blocks_when_unsafe(self):
        from agentiq_labclaw.orchestrator import post_execute, _get_config

        if hasattr(_get_config, '_cache'):
            del _get_config._cache

        output = MockSkillOutput(
            result_data={"test": 1},
            novel=False,
            critique_required=True,
            confidence_score=0.01,
        )

        # Safety check blocks because confidence < threshold and critique_required but not completed
        # We skip Claude to trigger "critique required but not completed"
        with patch("reviewer.claude_reviewer.ClaudeReviewer.critique", side_effect=Exception("API down")):
            result = await post_execute("test_skill", output, run_id=None)

        orch = result["orchestration"]
        # Safety blocks because run_id is None
        assert orch["safety"]["safe"] is False


class TestPostExecutePublishers:
    """Test publishing pipeline."""

    @pytest.mark.asyncio
    async def test_pdf_generation(self):
        from agentiq_labclaw.orchestrator import post_execute, _get_config

        if hasattr(_get_config, '_cache'):
            del _get_config._cache

        output = MockSkillOutput(result_data={"data": 1}, novel=False, critique_required=False)

        with patch("agentiq_labclaw.guardrails.safety_check.safety_check", return_value=(True, None)), \
             patch("agentiq_labclaw.publishers.pdf_publisher.PDFPublisher.generate_report", return_value="/tmp/report.pdf") as mock_pdf, \
             patch("agentiq_labclaw.publishers.github_publisher.GitHubPublisher.commit_result", return_value=True):

            result = await post_execute("test_skill", output, run_id=1)

        mock_pdf.assert_called_once()
        published = result["orchestration"]["published"]
        assert any("pdf:" in p for p in published)
