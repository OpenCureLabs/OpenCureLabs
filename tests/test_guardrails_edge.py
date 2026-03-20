"""Edge-case tests for guardrails: safety_check, novelty_filter, output_validator."""

import os
import sys
from unittest.mock import patch, MagicMock

import pytest
from pydantic import BaseModel, ValidationError

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "packages", "agentiq_labclaw"))

from agentiq_labclaw.guardrails.safety_check import safety_check, MINIMUM_CONFIDENCE
from agentiq_labclaw.guardrails.output_validator import validate_output


# ── Test schemas ──────────────────────────────────────────────────────────────

class SampleOutput(BaseModel):
    gene: str
    confidence_score: float | None = None
    critique_required: bool = False


class StrictOutput(BaseModel):
    gene: str
    score: float


# ═══════════════════════════════════════════════════════════════════════════
#  safety_check
# ═══════════════════════════════════════════════════════════════════════════

class TestSafetyCheck:
    """Edge cases for safety_check guardrail."""

    def test_passes_with_valid_output(self):
        output = SampleOutput(gene="TP53", confidence_score=0.9)
        ok, reason = safety_check(output, agent_run_id=1)
        assert ok is True
        assert reason is None

    def test_blocks_no_agent_run_id(self):
        output = SampleOutput(gene="TP53", confidence_score=0.9)
        ok, reason = safety_check(output, agent_run_id=None)
        assert ok is False
        assert "agent_run_id" in reason

    def test_blocks_confidence_below_threshold(self):
        output = SampleOutput(gene="TP53", confidence_score=0.05)
        ok, reason = safety_check(output, agent_run_id=1)
        assert ok is False
        assert "Confidence" in reason

    def test_passes_confidence_at_threshold(self):
        output = SampleOutput(gene="TP53", confidence_score=MINIMUM_CONFIDENCE)
        ok, reason = safety_check(output, agent_run_id=1)
        assert ok is True

    def test_confidence_zero(self):
        output = SampleOutput(gene="TP53", confidence_score=0.0)
        ok, reason = safety_check(output, agent_run_id=1)
        assert ok is False

    def test_passes_with_no_confidence_field(self):
        output = SampleOutput(gene="TP53")
        ok, reason = safety_check(output, agent_run_id=1)
        assert ok is True

    def test_blocks_critique_required_not_completed(self):
        output = SampleOutput(gene="TP53", confidence_score=0.9, critique_required=True)
        ok, reason = safety_check(output, agent_run_id=1, critique_completed=False)
        assert ok is False
        assert "critique" in reason.lower()

    def test_passes_critique_required_and_completed(self):
        output = SampleOutput(gene="TP53", confidence_score=0.9, critique_required=True)
        ok, reason = safety_check(output, agent_run_id=1, critique_completed=True)
        assert ok is True

    def test_negative_confidence(self):
        output = SampleOutput(gene="TP53", confidence_score=-0.5)
        ok, reason = safety_check(output, agent_run_id=1)
        assert ok is False

    def test_high_confidence_passes(self):
        output = SampleOutput(gene="TP53", confidence_score=1.0)
        ok, reason = safety_check(output, agent_run_id=1)
        assert ok is True


# ═══════════════════════════════════════════════════════════════════════════
#  novelty_filter
# ═══════════════════════════════════════════════════════════════════════════

class TestNoveltyFilter:
    """Tests for novelty_filter.check_novelty — mocks DB layer."""

    @patch("agentiq_labclaw.guardrails.novelty_filter.db_check_novelty")
    def test_novel_result(self, mock_db):
        from agentiq_labclaw.guardrails.novelty_filter import check_novelty
        mock_db.return_value = True
        assert check_novelty("neoantigen", {"gene": "TP53"}) is True

    @patch("agentiq_labclaw.guardrails.novelty_filter.db_check_novelty")
    def test_replication_result(self, mock_db):
        from agentiq_labclaw.guardrails.novelty_filter import check_novelty
        mock_db.return_value = False
        assert check_novelty("docking", {"score": 0.5}) is False

    @patch("agentiq_labclaw.guardrails.novelty_filter.db_check_novelty")
    def test_empty_result_data(self, mock_db):
        from agentiq_labclaw.guardrails.novelty_filter import check_novelty
        mock_db.return_value = True
        assert check_novelty("generic", {}) is True
        mock_db.assert_called_once_with("generic", {})


# ═══════════════════════════════════════════════════════════════════════════
#  output_validator
# ═══════════════════════════════════════════════════════════════════════════

class TestOutputValidator:
    """Edge cases for validate_output guardrail."""

    def test_valid_output_passes(self):
        output = StrictOutput(gene="TP53", score=0.9)
        ok, err = validate_output(output, StrictOutput)
        assert ok is True
        assert err is None

    def test_schema_mismatch_fails(self):
        """Pass an output that doesn't match the expected schema."""
        output = SampleOutput(gene="TP53", confidence_score=0.5)
        ok, err = validate_output(output, StrictOutput)
        assert ok is False
        assert "validation failed" in err.lower()

    def test_valid_with_optional_fields(self):
        output = SampleOutput(gene="BRCA1")
        ok, err = validate_output(output, SampleOutput)
        assert ok is True

    def test_roundtrip_preserves_data(self):
        output = StrictOutput(gene="KRAS", score=0.42)
        ok, _ = validate_output(output, StrictOutput)
        assert ok is True
        assert output.gene == "KRAS"
        assert output.score == 0.42
